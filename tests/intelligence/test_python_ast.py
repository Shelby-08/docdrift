from docsentry.intelligence.python_ast import (
    diff_symbol_signatures,
    extract_python_symbols,
)


def test_extract_python_symbols() -> None:
    code = """
class MyService:
    '''Service class'''
    def compute(self, a: int, b: str = 'def') -> bool:
        return True

def standalone() -> None:
    pass
"""
    symbols = extract_python_symbols(code)
    assert len(symbols) == 3
    names = {s.qualified_name for s in symbols}
    assert names == {"MyService", "MyService.compute", "standalone"}

    compute_sig = next(s for s in symbols if s.qualified_name == "MyService.compute")
    assert compute_sig.kind == "method"
    assert len(compute_sig.parameters) == 3
    assert compute_sig.parameters[1].name == "a"
    assert compute_sig.parameters[1].type_annotation == "int"
    assert compute_sig.parameters[2].name == "b"
    assert compute_sig.parameters[2].default_value == "'def'"
    assert compute_sig.return_type == "bool"


def test_diff_symbol_signatures() -> None:
    code_before = """
def process(x: int) -> int:
    '''old doc'''
    return x

def old_fn():
    pass
"""
    code_after = """
def process(x: int, y: int) -> int:
    '''old doc'''
    return x + y

def new_fn():
    pass
"""
    before_syms = extract_python_symbols(code_before)
    after_syms = extract_python_symbols(code_after)

    changes = diff_symbol_signatures("file.py", before_syms, after_syms)
    assert len(changes) == 3

    removed = next(c for c in changes if c.change_kind == "removed")
    assert removed.symbol_name == "old_fn"
    assert removed.breaking is True

    added = next(c for c in changes if c.change_kind == "added")
    assert added.symbol_name == "new_fn"
    assert added.breaking is False

    changed = next(c for c in changes if c.change_kind == "signature_changed")
    assert changed.symbol_name == "process"
    assert changed.breaking is True  # required param y without default
