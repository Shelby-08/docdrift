from docsentry.retrieval.classify import classify_path


def test_classify_path_docs() -> None:
    assert classify_path("README.md") == "doc"
    assert classify_path("docs/api.markdown") == "doc"
    assert classify_path("guides/intro.rst") == "doc"
    assert classify_path("nested/docs/guide.adoc") == "doc"
    assert classify_path("nested/docs/page.mdx") == "doc"
    assert classify_path("CONTRIBUTING") == "doc"
    assert classify_path("sub/CHANGELOG") == "doc"


def test_classify_path_source() -> None:
    for ext in (".py", ".ts", ".tsx", ".js", ".jsx", ".go", ".rs", ".cpp", ".c", ".h"):
        assert classify_path(f"src/main{ext}") == "source"


def test_classify_path_config() -> None:
    for ext in (".json", ".yaml", ".yml", ".toml", ".ini", ".cfg"):
        assert classify_path(f"config/settings{ext}") == "config"


def test_classify_path_ignored() -> None:
    assert classify_path("node_modules/pkg/README.md") == "other"
    assert classify_path(".venv/lib/python3.11/site.py") == "other"
    assert classify_path("vendor/bundle/gems/spec.rb") == "other"
    assert classify_path("dist/bundle.js") == "other"
    assert classify_path("build/out.json") == "other"
    assert classify_path(".git/HEAD") == "other"


def test_classify_path_other() -> None:
    assert classify_path("image.png") == "other"
    assert classify_path("data.csv") == "other"
    assert classify_path("binary.exe") == "other"
