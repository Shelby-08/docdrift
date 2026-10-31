import ast
import logging
from typing import Any

from docsentry.intelligence.models import (
    ChangeKind,
    ParameterInfo,
    SymbolChange,
    SymbolKind,
    SymbolSignature,
)

logger = logging.getLogger(__name__)


def _unparse(node: ast.AST | None) -> str | None:
    if node is None:
        return None
    try:
        return ast.unparse(node)
    except Exception:
        return None


class _SymbolExtractor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.symbols: list[SymbolSignature] = []
        self.scope_stack: list[str] = []

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        parent = ".".join(self.scope_stack)
        qname = f"{parent}.{node.name}" if parent else node.name
        docstring = ast.get_docstring(node)
        decorators = [_unparse(d) or "" for d in node.decorator_list]
        decorators = [d for d in decorators if d]

        sig = SymbolSignature(
            name=node.name,
            qualified_name=qname,
            kind="class",
            parameters=[],
            return_type=None,
            docstring=docstring,
            line_start=node.lineno,
            line_end=getattr(node, "end_lineno", node.lineno),
            decorators=decorators,
        )
        self.symbols.append(sig)

        self.scope_stack.append(node.name)
        self.generic_visit(node)
        self.scope_stack.pop()

    def _extract_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef, is_async: bool) -> None:
        parent = ".".join(self.scope_stack)
        qname = f"{parent}.{node.name}" if parent else node.name
        kind: SymbolKind = "method" if self.scope_stack else ("async_function" if is_async else "function")
        docstring = ast.get_docstring(node)
        decorators = [_unparse(d) or "" for d in node.decorator_list]
        decorators = [d for d in decorators if d]
        ret_type = _unparse(node.returns)

        # Parameters
        params: list[ParameterInfo] = []
        args = node.args

        # Positional only
        posonly_defaults_offset = len(args.posonlyargs) + len(args.args) - len(args.defaults)
        for idx, arg in enumerate(args.posonlyargs):
            default_idx = idx - (len(args.posonlyargs) + len(args.args) - len(args.defaults))
            default_val = _unparse(args.defaults[default_idx]) if default_idx >= 0 else None
            params.append(
                ParameterInfo(
                    name=arg.arg,
                    type_annotation=_unparse(arg.annotation),
                    default_value=default_val,
                    kind="positional_only",
                )
            )

        # Positional or keyword
        num_posonly = len(args.posonlyargs)
        for idx, arg in enumerate(args.args):
            global_idx = num_posonly + idx
            default_idx = global_idx - posonly_defaults_offset
            default_val = _unparse(args.defaults[default_idx]) if default_idx >= 0 else None
            params.append(
                ParameterInfo(
                    name=arg.arg,
                    type_annotation=_unparse(arg.annotation),
                    default_value=default_val,
                    kind="positional_or_keyword",
                )
            )

        # Var positional (*args)
        if args.vararg:
            params.append(
                ParameterInfo(
                    name=args.vararg.arg,
                    type_annotation=_unparse(args.vararg.annotation),
                    default_value=None,
                    kind="var_positional",
                )
            )

        # Keyword only
        for idx, arg in enumerate(args.kwonlyargs):
            default_node = args.kw_defaults[idx] if idx < len(args.kw_defaults) else None
            params.append(
                ParameterInfo(
                    name=arg.arg,
                    type_annotation=_unparse(arg.annotation),
                    default_value=_unparse(default_node),
                    kind="keyword_only",
                )
            )

        # Var keyword (**kwargs)
        if args.kwarg:
            params.append(
                ParameterInfo(
                    name=args.kwarg.arg,
                    type_annotation=_unparse(args.kwarg.annotation),
                    default_value=None,
                    kind="var_keyword",
                )
            )

        sig = SymbolSignature(
            name=node.name,
            qualified_name=qname,
            kind=kind,
            parameters=params,
            return_type=ret_type,
            docstring=docstring,
            line_start=node.lineno,
            line_end=getattr(node, "end_lineno", node.lineno),
            decorators=decorators,
        )
        self.symbols.append(sig)

        self.scope_stack.append(node.name)
        self.generic_visit(node)
        self.scope_stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._extract_function(node, is_async=False)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._extract_function(node, is_async=True)


def extract_python_symbols(source_code: str) -> list[SymbolSignature]:
    """Extract public and internal classes, functions, and methods from Python source using standard ast."""
    if not source_code.strip():
        return []
    try:
        root = ast.parse(source_code)
    except SyntaxError as exc:
        logger.warning("Syntax error parsing Python source: %s", exc)
        return []

    extractor = _SymbolExtractor()
    extractor.visit(root)
    return extractor.symbols


def diff_symbol_signatures(
    file_path: str,
    before_symbols: list[SymbolSignature],
    after_symbols: list[SymbolSignature],
) -> list[SymbolChange]:
    """Compute semantic symbol changes between two versions of a Python file."""
    before_map = {s.qualified_name: s for s in before_symbols}
    after_map = {s.qualified_name: s for s in after_symbols}

    changes: list[SymbolChange] = []

    # Removed symbols
    for qname, before in before_map.items():
        if qname not in after_map:
            changes.append(
                SymbolChange(
                    file_path=file_path,
                    symbol_name=before.name,
                    qualified_name=qname,
                    change_kind="removed",
                    before=before,
                    after=None,
                    breaking=not before.name.startswith("_"),
                    details=f"Symbol '{qname}' was removed",
                )
            )

    # Added or modified symbols
    for qname, after in after_map.items():
        if qname not in before_map:
            changes.append(
                SymbolChange(
                    file_path=file_path,
                    symbol_name=after.name,
                    qualified_name=qname,
                    change_kind="added",
                    before=None,
                    after=after,
                    breaking=False,
                    details=f"Symbol '{qname}' was added",
                )
            )
            continue

        before = before_map[qname]

        # Check signature changes (params, return type, kind)
        sig_changed = False
        is_breaking = False
        sig_details: list[str] = []

        if before.kind != after.kind:
            sig_changed = True
            sig_details.append(f"kind changed from {before.kind} to {after.kind}")

        if before.return_type != after.return_type:
            sig_changed = True
            sig_details.append(f"return type changed from {before.return_type} to {after.return_type}")
            if not after.name.startswith("_"):
                is_breaking = True

        # Parameter differences
        before_params = {p.name: p for p in before.parameters}
        after_params = {p.name: p for p in after.parameters}

        # Removed parameters
        for p_name, p_before in before_params.items():
            if p_name not in after_params:
                sig_changed = True
                is_breaking = True
                sig_details.append(f"parameter '{p_name}' removed")

        # Added parameters
        for p_name, p_after in after_params.items():
            if p_name not in before_params:
                sig_changed = True
                sig_details.append(f"parameter '{p_name}' added")
                if p_after.default_value is None and p_after.kind in ("positional_or_keyword", "positional_only", "keyword_only"):
                    is_breaking = True

        # Changed parameter types/defaults
        for p_name in set(before_params.keys()) & set(after_params.keys()):
            p_b = before_params[p_name]
            p_a = after_params[p_name]
            if p_b.type_annotation != p_a.type_annotation:
                sig_changed = True
                sig_details.append(f"parameter '{p_name}' type changed from {p_b.type_annotation} to {p_a.type_annotation}")
            if p_b.default_value != p_a.default_value:
                sig_changed = True
                sig_details.append(f"parameter '{p_name}' default changed from {p_b.default_value} to {p_a.default_value}")

        if sig_changed:
            changes.append(
                SymbolChange(
                    file_path=file_path,
                    symbol_name=after.name,
                    qualified_name=qname,
                    change_kind="signature_changed",
                    before=before,
                    after=after,
                    breaking=is_breaking and not after.name.startswith("_"),
                    details="; ".join(sig_details),
                )
            )
            continue

        # Check docstring changes
        if before.docstring != after.docstring:
            changes.append(
                SymbolChange(
                    file_path=file_path,
                    symbol_name=after.name,
                    qualified_name=qname,
                    change_kind="docstring_changed",
                    before=before,
                    after=after,
                    breaking=False,
                    details="Docstring was updated",
                )
            )

    return changes
