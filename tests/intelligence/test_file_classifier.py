from docsentry.intelligence.models.common import FileClass
from docsentry.intelligence.repository.file_classifier import classify_file


def test_classify_file_categories() -> None:
    # Source
    assert classify_file("src/docsentry/main.py") == FileClass.SOURCE

    # Test
    assert classify_file("tests/test_main.py") == FileClass.TEST
    assert classify_file("tests/conftest.py") == FileClass.TEST
    assert classify_file("src/tests/helper.py") == FileClass.TEST
    assert classify_file("src/main_test.py") == FileClass.TEST

    # Documentation
    assert classify_file("README.md") == FileClass.DOC
    assert classify_file("docs/guide.markdown") == FileClass.DOC

    # Unsupported
    assert classify_file("docs/spec.rst") == FileClass.UNSUPPORTED
    assert classify_file("docs/page.mdx") == FileClass.UNSUPPORTED
    assert classify_file("frontend/index.ts") == FileClass.UNSUPPORTED
    assert classify_file("backend/main.go") == FileClass.UNSUPPORTED

    # Config & Other
    assert classify_file(".env.example") == FileClass.CONFIG
    assert classify_file("node_modules/pkg/index.js") == FileClass.OTHER
    assert classify_file(".venv/lib/site.py") == FileClass.OTHER
