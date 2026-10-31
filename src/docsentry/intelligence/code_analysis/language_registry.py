from docsentry.intelligence.code_analysis.base import LanguageAdapter
from docsentry.intelligence.code_analysis.python_parser import parse_python
from docsentry.intelligence.models.code import ParsedSource


class PythonLanguageAdapter:
    language: str = "python"
    extensions: tuple[str, ...] = (".py", ".pyi")

    def parse(self, path: str, text: str, commit_sha: str) -> ParsedSource:
        return parse_python(path, text, commit_sha)


_PYTHON_ADAPTER = PythonLanguageAdapter()


def get_adapter(path: str) -> LanguageAdapter | None:
    if path.endswith((".py", ".pyi")):
        return _PYTHON_ADAPTER
    return None
