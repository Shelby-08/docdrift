import ast
import hashlib
import re

from docsentry.intelligence.code_analysis.value_extractor import (
    byte_offset_to_char_offset,
    extract_snippet,
    extract_value_repr,
)
from docsentry.intelligence.models.code import (
    Parameter,
)
from docsentry.intelligence.models.common import Provenance

RE_ALL_CAPS = re.compile(r"^[A-Z][A-Z0-9_]*$")


def _make_provenance(path: str, commit_sha: str, node: ast.AST, lines: list[str]) -> Provenance:
    lineno = getattr(node, "lineno", 1)
    end_lineno = getattr(node, "end_lineno", lineno)
    byte_col = getattr(node, "col_offset", 0)
    line_text = lines[lineno - 1] if 1 <= lineno <= len(lines) else ""
    char_col = byte_offset_to_char_offset(line_text, byte_col)
    snippet = extract_snippet(lines, lineno)
    return Provenance(
        path=path,
        commit_sha=commit_sha,
        line=lineno,
        end_line=end_lineno,
        column=char_col,
        snippet=snippet,
    )


def _make_entity_id(symbol_key: str, kind: str, line: int, col: int) -> str:
    raw = f"{symbol_key}:{kind}:{line}:{col}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _is_final(node: ast.AST | None) -> bool:
    if node is None:
        return False
    try:
        s = ast.unparse(node)
        return s == "Final" or s.startswith("Final[")
    except Exception:
        return False


def _extract_docstring(node: ast.AST) -> str | None:
    doc = ast.get_docstring(node)  # type: ignore[arg-type]
    if not doc:
        return None
    first_line = doc.strip().splitlines()[0].strip()
    return first_line[:200] if first_line else None


def _extract_params(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> tuple[Parameter, ...]:
    a = fn.args
    pos = [*a.posonlyargs, *a.args]
    pos_defaults: list[ast.expr | None] = [None] * (len(pos) - len(a.defaults)) + list(a.defaults)
    posonly_defs = pos_defaults[: len(a.posonlyargs)]
    regular_defs = pos_defaults[len(a.posonlyargs) :]

    params: list[Parameter] = []
    for arg, d in zip(a.posonlyargs, posonly_defs, strict=False):
        ann = ast.unparse(arg.annotation) if arg.annotation else None
        default_repr = extract_value_repr(d) if d is not None else None
        params.append(
            Parameter(name=arg.arg, kind="positional_only", default=default_repr, annotation=ann)
        )

    for arg, d in zip(a.args, regular_defs, strict=False):
        ann = ast.unparse(arg.annotation) if arg.annotation else None
        default_repr = extract_value_repr(d) if d is not None else None
        params.append(
            Parameter(
                name=arg.arg, kind="positional_or_keyword", default=default_repr, annotation=ann
            )
        )

    if a.vararg:
        ann = ast.unparse(a.vararg.annotation) if a.vararg.annotation else None
        params.append(Parameter(name=a.vararg.arg, kind="var_positional", annotation=ann))

    for arg, d in zip(a.kwonlyargs, a.kw_defaults, strict=False):
        ann = ast.unparse(arg.annotation) if arg.annotation else None
        default_repr = extract_value_repr(d) if d is not None else None
        params.append(
            Parameter(name=arg.arg, kind="keyword_only", default=default_repr, annotation=ann)
        )

    if a.kwarg:
        ann = ast.unparse(a.kwarg.annotation) if a.kwarg.annotation else None
        params.append(Parameter(name=a.kwarg.arg, kind="var_keyword", annotation=ann))

    return tuple(params)


def _check_config_call(node: ast.AST) -> tuple[str, ast.AST | None] | None:
    if not isinstance(node, ast.Call):
        return None
    fn = node.func
    is_getenv = False
    if isinstance(fn, ast.Name) and fn.id == "getenv":
        is_getenv = True
    elif isinstance(fn, ast.Attribute) and fn.attr == "getenv":
        if isinstance(fn.value, ast.Name) and fn.value.id == "os":
            is_getenv = True
    elif isinstance(fn, ast.Attribute) and fn.attr == "get":
        if isinstance(fn.value, ast.Attribute) and fn.value.attr == "environ":
            is_getenv = True
    if not is_getenv or not node.args:
        return None
    first_arg = node.args[0]
    if isinstance(first_arg, ast.Constant) and isinstance(first_arg.value, str):
        default_node = node.args[1] if len(node.args) > 1 else None
        return first_arg.value, default_node
    return None
