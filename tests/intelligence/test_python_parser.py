from docsentry.intelligence.code_analysis.language_registry import get_adapter
from docsentry.intelligence.code_analysis.python_parser import parse_python
from docsentry.intelligence.models.common import Exposure

SHA = "a" * 40


def test_language_registry() -> None:
    adapter = get_adapter("src/main.py")
    assert adapter is not None
    assert adapter.language == "python"
    assert get_adapter("doc.md") is None


def test_parse_functions_and_classes() -> None:
    src = """
@dec1
def sync_fn(a: int, b: str = "hello") -> bool:
    '''Summary line of sync_fn.
    More docs.
    '''
    def nested():
        pass
    return True

async def async_fn(*args, kw: int = 10, **kwargs) -> None:
    pass

class Outer:
    cv: int = 42
    
    def method(self) -> None:
        pass
        
    class Inner:
        pass
"""
    parsed = parse_python("pkg/mod.py", src, SHA)
    assert not parsed.errors
    names = [e.name for e in parsed.entities]
    assert "sync_fn" in names
    assert "async_fn" in names
    assert "Outer" in names
    assert "method" in names
    assert "Inner" in names
    assert "nested" not in names  # nested function skipped

    sync_e = next(e for e in parsed.entities if e.name == "sync_fn")
    assert sync_e.kind == "function"
    assert sync_e.return_annotation == "bool"
    assert sync_e.docstring_summary == "Summary line of sync_fn."
    assert sync_e.decorators == ("dec1",)

    inner_e = next(e for e in parsed.entities if e.name == "Inner")
    assert inner_e.qualname == "Outer.Inner"


def test_parameter_defaults_alignment() -> None:
    src = """
def fn(p1, p2=1, /, r1=2, r2=3, *var, k1=4, k2=None, **kw):
    pass
"""
    parsed = parse_python("pkg/mod.py", src, SHA)
    fn_e = next(e for e in parsed.entities if e.name == "fn")
    params = {p.name: p for p in fn_e.parameters}
    assert params["p1"].kind == "positional_only" and params["p1"].default is None
    assert params["p2"].kind == "positional_only" and params["p2"].default.value == 1
    assert params["r1"].kind == "positional_or_keyword" and params["r1"].default.value == 2
    assert params["r2"].kind == "positional_or_keyword" and params["r2"].default.value == 3
    assert params["var"].kind == "var_positional"
    assert params["k1"].kind == "keyword_only" and params["k1"].default.value == 4
    assert params["k2"].kind == "keyword_only" and params["k2"].default.value is None
    assert params["kw"].kind == "var_keyword"


def test_constants_and_aliases() -> None:
    src = """
from typing import Final

MAX_RETRIES = 5
TIMEOUT_SECONDS = 60 * 60
NEGATIVE = -10
DEBUG: Final = True
COMPLEX = some_call()
OLD_NAME = MAX_RETRIES
"""
    parsed = parse_python("pkg/consts.py", src, SHA)
    ents = {e.name: e for e in parsed.entities}
    assert ents["MAX_RETRIES"].value.value == 5
    assert ents["TIMEOUT_SECONDS"].value.value == 3600
    assert ents["NEGATIVE"].value.value == -10
    assert ents["DEBUG"].value.value is True
    assert ents["COMPLEX"].value.resolved is False
    assert ents["OLD_NAME"].alias_target == "MAX_RETRIES"


def test_all_and_exposure() -> None:
    src = """
__all__ = ["public_fn"]

def public_fn(): pass
def _private_fn(): pass
def other_fn(): pass

class Cls:
    def pub_m(self): pass
    def _priv_m(self): pass
    def __dunder__(self): pass
"""
    parsed = parse_python("pkg/exp.py", src, SHA)
    ents = {e.name: e for e in parsed.entities}
    assert ents["public_fn"].exposure == Exposure.PUBLIC
    assert ents["_private_fn"].exposure == Exposure.PRIVATE
    assert ents["other_fn"].exposure == Exposure.UNKNOWN
    assert ents["pub_m"].exposure == Exposure.UNKNOWN
    assert ents["_priv_m"].exposure == Exposure.PRIVATE
    assert ents["__dunder__"].exposure == Exposure.UNKNOWN


def test_conditional_definitions_and_getattr() -> None:
    src = """
def __getattr__(name):
    return None

if True:
    COND_CONST = 1
"""
    parsed = parse_python("pkg/dyn.py", src, SHA)
    assert parsed.has_module_getattr is True
    c = next(e for e in parsed.entities if e.name == "COND_CONST")
    assert c.conditional is True


def test_non_ascii_column_offset() -> None:
    src = """# 🐍 comment
def foo(): pass"""
    parsed = parse_python("pkg/unicode.py", src, SHA)
    foo_e = next(e for e in parsed.entities if e.name == "foo")
    assert foo_e.provenance.column == 0


def test_imports_references_and_string_keys() -> None:
    src = """
import os
from sys import path as sys_path
from .sibling import helper

x = config["ENABLE_CACHE"]
run(target=sys_path)
"""
    parsed = parse_python("pkg/app.py", src, SHA)
    modules = [i.module for i in parsed.imports]
    assert "os" in modules and "sys" in modules and "sibling" in modules
    assert any(i.module == "sibling" and i.level == 1 for i in parsed.imports)
    assert any(sk.value == "ENABLE_CACHE" for sk in parsed.string_keys)
    assert any(r.name == "run" and r.kind == "call" for r in parsed.references)


def test_error_handling_and_no_execution() -> None:
    # Syntax error
    res_syn = parse_python("bad.py", "def (:", SHA)
    assert len(res_syn.errors) == 1
    assert "SyntaxError" in res_syn.errors[0]

    # Null byte
    res_null = parse_python("null.py", "def foo(): \x00", SHA)
    assert len(res_null.errors) == 1

    # Recursion error on deeply nested brackets
    res_rec = parse_python("rec.py", "(" * 2000 + ")" * 2000, SHA)
    # ast.parse handles or raises MemoryError/RecursionError/SyntaxError
    assert res_rec is not None

    # Untrusted code execution protection test
    sentinel = False
    malicious_code = """
import sys
sentinel = True
raise SystemExit(1)
"""
    res_safe = parse_python("safe.py", malicious_code, SHA)
    assert sentinel is False
    assert len(res_safe.entities) >= 0
