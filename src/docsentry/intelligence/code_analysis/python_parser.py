import ast

from docsentry.intelligence.code_analysis.fact_extractor import facts_from_entities
from docsentry.intelligence.code_analysis.python_parser_helpers import (
    RE_ALL_CAPS,
    _check_config_call,
    _extract_docstring,
    _extract_params,
    _is_final,
    _make_entity_id,
    _make_provenance,
)
from docsentry.intelligence.code_analysis.value_extractor import extract_value_repr
from docsentry.intelligence.models.code import (
    CodeEntity,
    ImportRecord,
    ParsedSource,
    ReferenceRecord,
    StringKeyReference,
)
from docsentry.intelligence.models.common import Exposure


def _determine_exposure(
    name: str,
    all_names: tuple[str, ...] | None,
    is_method: bool = False,
    class_exposure: Exposure = Exposure.UNKNOWN,
) -> Exposure:
    if is_method:
        is_priv = name.startswith("_") and not (name.startswith("__") and name.endswith("__"))
        if class_exposure == Exposure.PRIVATE or is_priv:
            return Exposure.PRIVATE
        if name.startswith("__") and name.endswith("__"):
            return Exposure.UNKNOWN
        return Exposure.PUBLIC if class_exposure == Exposure.PUBLIC else Exposure.UNKNOWN

    if all_names is not None:
        if name in all_names:
            return Exposure.PUBLIC
        return Exposure.PRIVATE if name.startswith("_") else Exposure.UNKNOWN
    return Exposure.PRIVATE if name.startswith("_") else Exposure.UNKNOWN


class _ASTExtractor:
    def __init__(self, path: str, commit_sha: str, lines: list[str], tree: ast.Module) -> None:
        self.path = path
        self.commit_sha = commit_sha
        self.lines = lines
        self.tree = tree
        self.entities: list[CodeEntity] = []
        self.imports: list[ImportRecord] = []
        self.references: list[ReferenceRecord] = []
        self.string_keys: list[StringKeyReference] = []
        self.has_module_getattr = False
        self.all_names: tuple[str, ...] | None = self._extract_all_names()

    def _extract_all_names(self) -> tuple[str, ...] | None:
        names: list[str] = []
        valid = False
        for node in self.tree.body:
            if isinstance(node, ast.Assign):
                for t in node.targets:
                    if isinstance(t, ast.Name) and t.id == "__all__":
                        if isinstance(node.value, (ast.List, ast.Tuple)):
                            for elt in node.value.elts:
                                if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                                    names.append(elt.value)
                                else:
                                    return None
                            valid = True
                        else:
                            return None
            elif isinstance(node, ast.AugAssign):
                if isinstance(node.target, ast.Name) and node.target.id == "__all__":
                    if isinstance(node.value, (ast.List, ast.Tuple)):
                        for elt in node.value.elts:
                            if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                                names.append(elt.value)
                            else:
                                return None
                    else:
                        return None
        return tuple(names) if valid else None

    def run(self) -> None:
        self._walk_body(self.tree.body, conditional=False, container_id=None, prefix="")
        self._extract_references()

    def _walk_body(
        self,
        body: list[ast.stmt],
        conditional: bool,
        container_id: str | None,
        prefix: str,
        class_exposure: Exposure = Exposure.UNKNOWN,
    ) -> None:
        for stmt in body:
            if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self._handle_function(stmt, conditional, container_id, prefix, class_exposure)
            elif isinstance(stmt, ast.ClassDef):
                self._handle_class(stmt, conditional, prefix)
            elif isinstance(stmt, (ast.Assign, ast.AnnAssign)):
                self._handle_assign(stmt, conditional, container_id, prefix)
            elif isinstance(stmt, (ast.If, ast.Try)):
                for sub in getattr(stmt, "body", []):
                    self._walk_body([sub], True, container_id, prefix, class_exposure)
                for sub in getattr(stmt, "orelse", []):
                    self._walk_body([sub], True, container_id, prefix, class_exposure)
            elif isinstance(stmt, ast.Import):
                for alias in stmt.names:
                    prov = _make_provenance(self.path, self.commit_sha, stmt, self.lines)
                    self.imports.append(
                        ImportRecord(
                            path=self.path,
                            module=alias.name,
                            alias=alias.asname,
                            level=0,
                            provenance=prov,
                        )
                    )
            elif isinstance(stmt, ast.ImportFrom):
                for alias in stmt.names:
                    prov = _make_provenance(self.path, self.commit_sha, stmt, self.lines)
                    self.imports.append(
                        ImportRecord(
                            path=self.path,
                            module=stmt.module,
                            name=alias.name,
                            alias=alias.asname,
                            level=stmt.level,
                            provenance=prov,
                        )
                    )

    def _handle_function(
        self,
        stmt: ast.FunctionDef | ast.AsyncFunctionDef,
        conditional: bool,
        container_id: str | None,
        prefix: str,
        class_exposure: Exposure,
    ) -> None:
        if container_id is None and stmt.name == "__getattr__":
            self.has_module_getattr = True
        qualname = f"{prefix}{stmt.name}"
        sym_key = f"{self.path}::{qualname}"
        prov = _make_provenance(self.path, self.commit_sha, stmt, self.lines)
        kind = "method" if container_id else "function"
        ent_id = _make_entity_id(sym_key, kind, prov.line, prov.column or 0)
        exposure = _determine_exposure(
            stmt.name,
            self.all_names,
            is_method=bool(container_id),
            class_exposure=class_exposure,
        )
        ret_ann = ast.unparse(stmt.returns) if stmt.returns else None
        decs = tuple(ast.unparse(d)[:60] for d in stmt.decorator_list)
        entity = CodeEntity(
            id=ent_id,
            symbol_key=sym_key,
            kind=kind,
            name=stmt.name,
            qualname=qualname,
            path=self.path,
            container_id=container_id,
            exposure=exposure,
            conditional=conditional,
            decorators=decs,
            docstring_summary=_extract_docstring(stmt),
            provenance=prov,
            parameters=_extract_params(stmt),
            return_annotation=ret_ann,
            is_async=isinstance(stmt, ast.AsyncFunctionDef),
        )
        self.entities.append(entity)

    def _handle_class(self, stmt: ast.ClassDef, conditional: bool, prefix: str) -> None:
        qualname = f"{prefix}{stmt.name}"
        sym_key = f"{self.path}::{qualname}"
        prov = _make_provenance(self.path, self.commit_sha, stmt, self.lines)
        ent_id = _make_entity_id(sym_key, "class", prov.line, prov.column or 0)
        exposure = _determine_exposure(stmt.name, self.all_names)
        bases = tuple(ast.unparse(b) for b in stmt.bases)
        decs = tuple(ast.unparse(d)[:60] for d in stmt.decorator_list)
        cls_entity = CodeEntity(
            id=ent_id,
            symbol_key=sym_key,
            kind="class",
            name=stmt.name,
            qualname=qualname,
            path=self.path,
            exposure=exposure,
            conditional=conditional,
            decorators=decs,
            docstring_summary=_extract_docstring(stmt),
            provenance=prov,
            bases=bases,
        )
        self.entities.append(cls_entity)
        self._walk_body(
            stmt.body,
            conditional,
            container_id=ent_id,
            prefix=f"{qualname}.",
            class_exposure=exposure,
        )

    def _handle_assign(
        self,
        stmt: ast.Assign | ast.AnnAssign,
        conditional: bool,
        container_id: str | None,
        prefix: str,
    ) -> None:
        target_name: str | None = None
        value_node: ast.AST | None = None
        ann_str: str | None = None
        if isinstance(stmt, ast.Assign):
            if len(stmt.targets) == 1 and isinstance(stmt.targets[0], ast.Name):
                target_name = stmt.targets[0].id
                value_node = stmt.value
        elif isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
            target_name = stmt.target.id
            value_node = stmt.value
            ann_str = ast.unparse(stmt.annotation)

        if not target_name:
            return

        prov = _make_provenance(self.path, self.commit_sha, stmt, self.lines)
        # Check config call
        if value_node is not None:
            cfg = _check_config_call(value_node)
            if cfg is not None:
                cfg_name, cfg_def = cfg
                cfg_sym = f"{self.path}::{cfg_name}"
                cfg_id = _make_entity_id(cfg_sym, "config_key", prov.line, prov.column or 0)
                val_repr = extract_value_repr(cfg_def) if cfg_def is not None else None
                self.entities.append(
                    CodeEntity(
                        id=cfg_id,
                        symbol_key=cfg_sym,
                        kind="config_key",
                        name=cfg_name,
                        qualname=cfg_name,
                        path=self.path,
                        container_id=container_id,
                        exposure=Exposure.PUBLIC,
                        conditional=conditional,
                        provenance=prov,
                        value=val_repr,
                    )
                )

        if container_id is not None:
            qualname = f"{prefix}{target_name}"
            sym_key = f"{self.path}::{qualname}"
            ent_id = _make_entity_id(sym_key, "class_variable", prov.line, prov.column or 0)
            val_repr = extract_value_repr(value_node) if value_node is not None else None
            self.entities.append(
                CodeEntity(
                    id=ent_id,
                    symbol_key=sym_key,
                    kind="class_variable",
                    name=target_name,
                    qualname=qualname,
                    path=self.path,
                    container_id=container_id,
                    exposure=Exposure.PUBLIC,
                    conditional=conditional,
                    provenance=prov,
                    value=val_repr,
                    annotation=ann_str,
                )
            )
            return

        # Module level constant or alias
        is_const = bool(RE_ALL_CAPS.match(target_name)) or _is_final(
            stmt.annotation if isinstance(stmt, ast.AnnAssign) else None
        )
        alias_target = value_node.id if isinstance(value_node, ast.Name) else None
        if is_const or alias_target:
            sym_key = f"{self.path}::{target_name}"
            ent_id = _make_entity_id(sym_key, "constant", prov.line, prov.column or 0)
            exposure = _determine_exposure(target_name, self.all_names)
            val_repr = extract_value_repr(value_node) if value_node is not None else None
            self.entities.append(
                CodeEntity(
                    id=ent_id,
                    symbol_key=sym_key,
                    kind="constant",
                    name=target_name,
                    qualname=target_name,
                    path=self.path,
                    container_id=None,
                    exposure=exposure,
                    conditional=conditional,
                    provenance=prov,
                    value=val_repr,
                    annotation=ann_str,
                    alias_target=alias_target,
                )
            )

    def _extract_references(self) -> None:
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Call):
                fn = node.func
                name = (
                    fn.id
                    if isinstance(fn, ast.Name)
                    else (fn.attr if isinstance(fn, ast.Attribute) else None)
                )
                if name:
                    prov = _make_provenance(self.path, self.commit_sha, node, self.lines)
                    self.references.append(
                        ReferenceRecord(path=self.path, name=name, kind="call", provenance=prov)
                    )
            elif isinstance(node, ast.Subscript):
                sl = node.slice
                if isinstance(sl, ast.Constant) and isinstance(sl.value, str):
                    prov = _make_provenance(self.path, self.commit_sha, node, self.lines)
                    self.string_keys.append(
                        StringKeyReference(path=self.path, value=sl.value, provenance=prov)
                    )


def parse_python(path: str, text: str, commit_sha: str) -> ParsedSource:
    try:
        tree = ast.parse(text, filename=path)
    except (SyntaxError, ValueError, RecursionError, MemoryError) as e:
        line = getattr(e, "lineno", 0) or 0
        err = f"{type(e).__name__} at line {line}"
        return ParsedSource(path=path, commit_sha=commit_sha, language="python", errors=(err,))

    lines = text.splitlines()
    extractor = _ASTExtractor(path, commit_sha, lines, tree)
    extractor.run()
    facts = tuple(facts_from_entities(extractor.entities))
    return ParsedSource(
        path=path,
        commit_sha=commit_sha,
        language="python",
        entities=tuple(extractor.entities),
        facts=facts,
        imports=tuple(extractor.imports),
        references=tuple(extractor.references),
        string_keys=tuple(extractor.string_keys),
        all_names=extractor.all_names,
        has_module_getattr=extractor.has_module_getattr,
    )
