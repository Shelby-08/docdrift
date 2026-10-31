import ast

from docsentry.intelligence.models.common import ValueRepr

MAGNITUDE_CAP = 10**12


def eval_numeric_expr(node: ast.AST) -> int | float | None:
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
            return node.value
        return None
    if isinstance(node, ast.UnaryOp):
        sub = eval_numeric_expr(node.operand)
        if sub is None:
            return None
        if isinstance(node.op, ast.USub):
            return -sub
        if isinstance(node.op, ast.UAdd):
            return sub
        return None
    if isinstance(node, ast.BinOp):
        left = eval_numeric_expr(node.left)
        right = eval_numeric_expr(node.right)
        if left is None or right is None:
            return None
        try:
            res: int | float
            if isinstance(node.op, ast.Add):
                res = left + right
            elif isinstance(node.op, ast.Sub):
                res = left - right
            elif isinstance(node.op, ast.Mult):
                res = left * right
            elif isinstance(node.op, ast.FloorDiv):
                if right == 0:
                    return None
                res = left // right
            elif isinstance(node.op, ast.Div):
                if right == 0:
                    return None
                res = left / right
            else:
                return None
            if abs(res) > MAGNITUDE_CAP:
                return None
            return res
        except Exception:
            return None
    return None


def extract_value_repr(node: ast.AST) -> ValueRepr:
    try:
        source_expr = ast.unparse(node)[:200]
    except Exception:
        source_expr = ""
    try:
        val = ast.literal_eval(node)
        if isinstance(val, (int, float, str, bool, type(None))):
            return ValueRepr(resolved=True, value=val, source_expr=source_expr)
        if isinstance(val, (list, tuple)):
            return ValueRepr(resolved=True, value=list(val), source_expr=source_expr)
        if isinstance(val, dict):
            return ValueRepr(resolved=True, value=val, source_expr=source_expr)
    except Exception:
        pass

    num = eval_numeric_expr(node)
    if num is not None:
        return ValueRepr(resolved=True, value=num, source_expr=source_expr)
    return ValueRepr(resolved=False, value=None, source_expr=source_expr)


def extract_unit_hint(name: str) -> str | None:
    upper = name.upper()
    for sfx in ("_MS", "_MILLISECONDS"):
        if upper.endswith(sfx):
            return "ms"
    for sfx in ("_SECONDS", "_SECS", "_SEC", "_S"):
        if upper.endswith(sfx):
            return "s"
    for sfx in ("_MINUTES", "_MINS"):
        if upper.endswith(sfx):
            return "min"
    for sfx in ("_HOURS", "_HOUR", "_H"):
        if upper.endswith(sfx):
            return "h"
    for sfx in ("_DAYS", "_DAY", "_D"):
        if upper.endswith(sfx):
            return "d"
    return None


def byte_offset_to_char_offset(line_text: str, byte_offset: int) -> int:
    if byte_offset <= 0:
        return 0
    encoded = line_text.encode("utf-8")
    if byte_offset >= len(encoded):
        return len(line_text)
    return len(encoded[:byte_offset].decode("utf-8", errors="replace"))


def extract_snippet(lines: list[str], lineno: int, max_len: int = 120) -> str | None:
    if 1 <= lineno <= len(lines):
        raw = lines[lineno - 1].strip()
        norm = " ".join(raw.split())
        return norm[:max_len] if norm else None
    return None
