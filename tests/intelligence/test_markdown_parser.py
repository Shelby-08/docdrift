from docsentry.intelligence.documentation.markdown_parser import classify_link, parse_markdown
from docsentry.intelligence.documentation.sentence_extractor import normalize_ws

SHA = "a" * 40


def parse(text: str, path: str = "docs/guide.md"):  # type: ignore[no-untyped-def]
    return parse_markdown(path, text, SHA)


def assert_offsets(text: str, doc) -> None:  # type: ignore[no-untyped-def]
    for st in doc.statements:
        assert normalize_ws(text[st.raw_start : st.raw_end]) == st.text
        assert st.location_verified


def texts(doc) -> list[str]:  # type: ignore[no-untyped-def]
    return [s.text for s in doc.statements]


def test_headings_hierarchy_and_paragraph() -> None:
    text = "# Top\n\nIntro text.\n\n## Sub\n\nSub text. More.\n\n# Next\n\nEnd"
    doc = parse(text)
    heads = [b for b in doc.blocks if b.kind == "heading"]
    assert [b.heading_path for b in heads] == [("Top",), ("Top", "Sub"), ("Next",)]
    para = [s for s in doc.statements if s.text == "Sub text."][0]
    assert para.heading_path == ("Top", "Sub")
    assert para.line == 7
    assert texts(doc)[-1] == "End"
    assert_offsets(text, doc)


def test_nested_lists_no_duplicates() -> None:
    text = "- one item.\n  - nested item.\n- two item.\n"
    doc = parse(text)
    assert texts(doc).count("nested item.") == 1
    assert sorted(texts(doc)) == ["nested item.", "one item.", "two item."]
    assert all(b.container for b in doc.blocks)
    assert_offsets(text, doc)


def test_blockquote() -> None:
    text = "> Quoted sentence here. Second one.\n"
    doc = parse(text)
    assert texts(doc) == ["Quoted sentence here.", "Second one."]
    assert doc.blocks[0].container == ("blockquote",)
    assert_offsets(text, doc)


def test_table_rows_and_escaped_pipe() -> None:
    text = "| Option | Default |\n|---|---|\n| `timeout` | 30 |\n| a\\|b | 5 |\n"
    doc = parse(text)
    assert doc.tables[0].header == ("Option", "Default")
    row = doc.tables[0].rows[0]
    assert row[0].text == "`timeout`" and row[1].text == "30"
    assert row[1].line == 3 and row[1].line_verified
    assert doc.tables[0].rows[1][0].text == "a|b"
    assert len(doc.tables[0].rows[1]) == 2
    assert [b.kind for b in doc.blocks].count("table_row") == 3


def test_inline_code_decimals_abbreviations_urls() -> None:
    text = (
        "Use `a. B` here. Version 3.11 is required. Next.\n\n"
        "See e.g. the docs. Visit https://example.com/a.b. Then stop. Check config.py. Done.\n"
    )
    doc = parse(text)
    assert texts(doc) == [
        "Use `a. B` here.",
        "Version 3.11 is required.",
        "Next.",
        "See e.g. the docs.",
        "Visit https://example.com/a.b.",
        "Then stop.",
        "Check config.py.",
        "Done.",
    ]
    assert_offsets(text, doc)


def test_unicode_offsets_and_multiline() -> None:
    text = "# Überschrift\n\nDer Wert ist 30 – schön. Zweiter\nSatz hier.\n"
    doc = parse(text)
    assert "Zweiter Satz hier." in texts(doc)
    two = [s for s in doc.statements if s.text.startswith("Zweiter")][0]
    assert two.line == 3 and two.end_line == 4
    assert_offsets(text, doc)


def test_fence_has_no_statements_and_identifiers() -> None:
    text = "Intro.\n\n```python\nfrom pkg import thing\nMAX_RETRIES = 3\nrun(x)\n```\n"
    doc = parse(text)
    assert texts(doc) == ["Intro."]
    cb = doc.code_blocks[0]
    assert cb.language == "python"
    assert {"run", "MAX_RETRIES", "pkg", "thing"} <= set(cb.identifiers)


def test_malformed_markdown_does_not_crash() -> None:
    for text in ["```python\nunclosed", "| a | b\n|--\n| 1", "", "\n\n", "[x]: \n", "- \n-\n"]:
        doc = parse(text)
        assert doc.path == "docs/guide.md"


def test_front_matter_skipped() -> None:
    text = "---\ntitle: X\n---\n\nReal text.\n"
    doc = parse(text)
    assert texts(doc) == ["Real text."]
    assert "front_matter_skipped" in doc.errors
    assert doc.statements[0].line == 5
    assert_offsets(text, doc)


def test_links_classification() -> None:
    text = (
        "See [cfg](../src/config.py), [anchor](#x), [ext](https://a.io), "
        "[mail](mailto:a@b.c) and [ref][r].\n\n[r]: ./other.md\n"
    )
    doc = parse(text, "docs/guide.md")
    by_target = {lk.target: lk for lk in doc.links}
    assert by_target["../src/config.py"].resolved_path == "src/config.py"
    assert by_target["../src/config.py"].kind == "relative_path"
    assert by_target["#x"].kind == "anchor"
    assert by_target["https://a.io"].kind == "external"
    assert by_target["mailto:a@b.c"].kind == "other"
    assert by_target["./other.md"].resolved_path == "docs/other.md"
    assert classify_link("a.md", "../../x.md")[1] is None


def test_paragraph_start_and_end_without_newline() -> None:
    text = "Start sentence. End sentence"
    doc = parse(text)
    assert texts(doc) == ["Start sentence.", "End sentence"]
    assert doc.statements[0].raw_start == 0
    assert_offsets(text, doc)
