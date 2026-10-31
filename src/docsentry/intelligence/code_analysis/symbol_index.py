import posixpath
from collections.abc import Sequence

from docsentry.intelligence.code_analysis.fact_extractor import facts_from_entities
from docsentry.intelligence.models.code import CodeEntity, ImportRecord, Parameter, ParsedSource
from docsentry.intelligence.models.common import ValueRepr


def resolve_import(importing_path: str, record: ImportRecord, paths: frozenset[str]) -> str | None:
    """Conservative import resolution on file paths."""
    mod_part = (record.module or "").replace(".", "/")

    if record.level > 0:
        # Relative import
        cur_dir = posixpath.dirname(importing_path)
        # level 1 is cur_dir, level 2 is parent, etc.
        for _ in range(record.level - 1):
            cur_dir = posixpath.dirname(cur_dir)

        if mod_part:
            base_target = posixpath.normpath(posixpath.join(cur_dir, mod_part))
            candidates = [f"{base_target}.py", f"{base_target}/__init__.py"]
        else:
            base_target = posixpath.normpath(cur_dir)
            candidates = [f"{base_target}/__init__.py"]

        matches = [c for c in candidates if c in paths]
        return matches[0] if len(matches) == 1 else None

    # Absolute import (level == 0)
    if not mod_part:
        return None

    roots = ["", "src/"]
    candidates = []
    for root in roots:
        target = posixpath.normpath(posixpath.join(root, mod_part))
        candidates.append(f"{target}.py")
        candidates.append(f"{target}/__init__.py")

    matches = [c for c in candidates if c in paths]
    return matches[0] if len(matches) == 1 else None


class SymbolIndex:
    def __init__(self, parsed_sources: Sequence[ParsedSource], paths: Sequence[str]) -> None:
        self.paths: frozenset[str] = frozenset(paths)
        self.sources_by_path: dict[str, ParsedSource] = {s.path: s for s in parsed_sources}
        self.by_id: dict[str, CodeEntity] = {}
        self.by_name: dict[str, list[str]] = {}
        self.by_path: dict[str, list[str]] = {}
        self.by_sym_key: dict[str, str] = {}
        self.all_exported_names: set[str] = set()

        for src in parsed_sources:
            if src.all_names:
                self.all_exported_names.update(src.all_names)
            self.by_path[src.path] = []
            for ent in src.entities:
                self.by_id[ent.id] = ent
                self.by_sym_key[ent.symbol_key] = ent.id
                self.by_name.setdefault(ent.name, []).append(ent.id)
                self.by_path[src.path].append(ent.id)

    def exists_in(self, name: str) -> bool:
        return name in self.by_name or name in self.all_exported_names

    def resolve_name(self, path: str, name: str) -> str | None:
        """Resolve an entity id from a name in a given file path."""
        # 1. Same-file definition first
        same_file_ids = [eid for eid in self.by_path.get(path, []) if self.by_id[eid].name == name]
        if len(same_file_ids) == 1:
            ent = self.by_id[same_file_ids[0]]
            if ent.alias_target:
                # One alias hop
                hop_ids = [
                    eid
                    for eid in self.by_path.get(path, [])
                    if self.by_id[eid].name == ent.alias_target
                ]
                if len(hop_ids) == 1:
                    return hop_ids[0]
            return ent.id
        elif len(same_file_ids) > 1:
            return None

        # 2. Check imports in this file
        src = self.sources_by_path.get(path)
        if not src:
            return None

        candidate_eids: list[str] = []
        for imp in src.imports:
            target_name: str | None = None
            if imp.alias == name:
                target_name = imp.name or imp.module
            elif imp.name == name:
                target_name = imp.name

            if target_name:
                target_file = resolve_import(path, imp, self.paths)
                if target_file and target_file in self.by_path:
                    file_eids = [
                        eid
                        for eid in self.by_path[target_file]
                        if self.by_id[eid].name == target_name
                    ]
                    if len(file_eids) == 1:
                        target_ent = self.by_id[file_eids[0]]
                        # Follow at most one alias hop
                        if target_ent.alias_target:
                            hop_ids = [
                                eid
                                for eid in self.by_path[target_file]
                                if self.by_id[eid].name == target_ent.alias_target
                            ]
                            if len(hop_ids) == 1:
                                candidate_eids.append(hop_ids[0])
                                continue
                        candidate_eids.append(target_ent.id)

        if len(candidate_eids) == 1:
            return candidate_eids[0]
        return None


def resolve_value_references(
    parsed_sources: Sequence[ParsedSource], index: SymbolIndex
) -> tuple[ParsedSource, ...]:
    """Post-process parameter defaults and constants to resolve Name references."""
    updated_sources: list[ParsedSource] = []

    for src in parsed_sources:
        new_entities: list[CodeEntity] = []
        changed = False

        for ent in src.entities:
            ent_changed = False
            new_params: list[Parameter] = []
            for p in ent.parameters:
                if p.default and not p.default.resolved and p.default.source_expr:
                    # Try resolving source_expr
                    target_id = index.resolve_name(src.path, p.default.source_expr)
                    if target_id and target_id in index.by_id:
                        target_ent = index.by_id[target_id]
                        if target_ent.value and target_ent.value.resolved:
                            new_vr = ValueRepr(
                                resolved=True,
                                value=target_ent.value.value,
                                source_expr=p.default.source_expr,
                                resolved_via=target_ent.id,
                            )
                            new_params.append(p.model_copy(update={"default": new_vr}))
                            ent_changed = True
                            continue
                new_params.append(p)

            new_val: ValueRepr | None = ent.value
            if (
                ent.kind == "constant"
                and ent.value
                and not ent.value.resolved
                and ent.value.source_expr
            ):
                target_id = index.resolve_name(src.path, ent.value.source_expr)
                if target_id and target_id in index.by_id:
                    target_ent = index.by_id[target_id]
                    if target_ent.value and target_ent.value.resolved:
                        new_val = ValueRepr(
                            resolved=True,
                            value=target_ent.value.value,
                            source_expr=ent.value.source_expr,
                            resolved_via=target_ent.id,
                        )
                        ent_changed = True

            if ent_changed:
                changed = True
                new_entities.append(
                    ent.model_copy(update={"parameters": tuple(new_params), "value": new_val})
                )
            else:
                new_entities.append(ent)

        if changed:
            new_facts = tuple(facts_from_entities(new_entities))
            updated_sources.append(
                src.model_copy(update={"entities": tuple(new_entities), "facts": new_facts})
            )
        else:
            updated_sources.append(src)

    return tuple(updated_sources)
