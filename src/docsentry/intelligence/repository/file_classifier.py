import os

from docsentry.intelligence.models.common import FileClass
from docsentry.retrieval.classify import classify_path

_TEST_FILE_NAMES = frozenset({"conftest.py"})
_DOC_EXTENSIONS = frozenset({".md", ".markdown"})
_UNSUPPORTED_DOC_EXTS = frozenset({".mdx", ".rst", ".adoc", ".asciidoc"})
_PYTHON_EXTENSIONS = frozenset({".py"})
_UNSUPPORTED_SOURCE_EXTS = frozenset({
    ".js", ".jsx", ".ts", ".tsx", ".go", ".rs", ".java", ".c", ".cpp", ".rb", ".php"
})


def classify_file(path: str) -> FileClass:
    norm = path.replace("\\", "/").strip("/")
    base_name = os.path.basename(norm).lower()
    parts = [p.lower() for p in norm.split("/")]
    _, ext = os.path.splitext(norm)
    ext = ext.lower()

    # Vendored / build / ignored
    for part in parts:
        if part in {"node_modules", "vendor", ".git", "dist", "build", ".venv"}:
            return FileClass.OTHER

    # Test classification
    if any(part in ("test", "tests", "__tests__", "testing") for part in parts[:-1]):
        return FileClass.TEST
    if (
        base_name in _TEST_FILE_NAMES
        or base_name.startswith("test_")
        or base_name.endswith("_test.py")
    ):
        return FileClass.TEST

    # Documentation
    if ext in _DOC_EXTENSIONS:
        return FileClass.DOC
    if ext in _UNSUPPORTED_DOC_EXTS:
        return FileClass.UNSUPPORTED

    # Python Source
    if ext in _PYTHON_EXTENSIONS:
        return FileClass.SOURCE
    if ext in _UNSUPPORTED_SOURCE_EXTS:
        return FileClass.UNSUPPORTED

    # Config files
    base_class = classify_path(norm)
    if base_name.startswith(".env") or base_class == "config":
        return FileClass.CONFIG

    return FileClass.OTHER
