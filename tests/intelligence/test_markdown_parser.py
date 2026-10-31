from docsentry.intelligence.markdown_parser import (
    extract_claims_from_blocks,
    parse_markdown_blocks,
)


def test_parse_markdown_and_extract_claims() -> None:
    md_text = """# API Reference

Use `process_data` to clean the dataset.

```python
def process_data(records: list) -> int:
    return len(records)
```

## Details

Call `MyService.run()` for starting the background worker.
"""
    blocks = parse_markdown_blocks("docs/api.md", md_text)
    assert len(blocks) >= 3

    claims = extract_claims_from_blocks(blocks)
    targets = {c.target_symbol for c in claims}
    assert "process_data" in targets
    assert "MyService.run" in targets

    sig_quote = next(c for c in claims if c.claim_kind == "signature_quote")
    assert sig_quote.target_symbol == "process_data"
    assert "def process_data" in sig_quote.extracted_text
