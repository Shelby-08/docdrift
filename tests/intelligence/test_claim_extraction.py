import pytest

from docsentry.intelligence.documentation.claim_extractor import extract_claims, subject_tokens
from docsentry.intelligence.documentation.markdown_parser import parse_markdown
from docsentry.intelligence.models.common import Certainty
from docsentry.intelligence.models.documentation import ClaimType

SHA = "a" * 40


def claims_for(text: str, path: str = "docs/c.md"):  # type: ignore[no-untyped-def]
    return extract_claims(parse_markdown(path, text, SHA))


def one(text: str, ctype: ClaimType):  # type: ignore[no-untyped-def]
    found = [c for c in claims_for(text) if c.claim_type == ctype]
    assert len(found) == 1, found
    return found[0]


def test_default_timeout_golden() -> None:
    c = one("Intro.\n\nThe default timeout is 30 seconds.\n", ClaimType.CONFIGURATION_DEFAULT)
    assert (c.subject, c.value, c.unit, c.certainty) == ("timeout", 30, "seconds", Certainty.MEDIUM)
    assert c.original_text == "The default timeout is 30 seconds."
    assert c.line == 3 and c.location_verified


def test_code_ident_default_high() -> None:
    c = one("`DEFAULT_TIMEOUT` defaults to 30 seconds.", ClaimType.CONFIGURATION_DEFAULT)
    assert c.subject == "DEFAULT_TIMEOUT" and c.certainty == Certainty.HIGH and c.value == 30


def test_default_value_of() -> None:
    c = one("The default value of max_retries is 3.", ClaimType.CONFIGURATION_DEFAULT)
    assert (c.subject, c.value, c.unit) == ("max_retries", 3, None)
    assert c.subject_tokens == ("max", "retries")


def test_api_signature() -> None:
    c = one(
        "Use `create_client(timeout, retries)` to initialize the client.", ClaimType.API_SIGNATURE
    )
    assert c.subject == "create_client" and c.parameters == ("timeout", "retries")


def test_configuration_reference() -> None:
    c = one("Set MAX_RETRIES to control the number of attempts.", ClaimType.CONFIGURATION_REFERENCE)
    assert c.subject == "MAX_RETRIES"


def test_parameter_mention() -> None:
    c = one("The `priority` parameter sets the message priority.", ClaimType.PARAMETER_MENTION)
    assert c.subject == "priority"


def test_http_method() -> None:
    c = one("Sends a POST request to the server.", ClaimType.HTTP_METHOD)
    assert c.value == "POST"
    assert not [
        x for x in claims_for("Sends a Post request.") if x.claim_type == ClaimType.HTTP_METHOD
    ]


def test_return_type_and_version() -> None:
    assert one("The function returns `int`.", ClaimType.RETURN_TYPE).value == "int"
    v = one("Requires Python 3.9 or newer.", ClaimType.VERSION_STATEMENT)
    assert v.value == "3.9"


def test_behavioral_candidate_has_no_number() -> None:
    cs = claims_for("The client intelligently retries failed requests.")
    assert [c.claim_type for c in cs] == [ClaimType.BEHAVIORAL_CANDIDATE]
    assert cs[0].value is None


def test_table_default_with_cell_location() -> None:
    text = "| Option | Default |\n|---|---|\n| `timeout` | 30s |\n| `retries` | 3 |\n"
    cs = [c for c in claims_for(text) if c.claim_type == ClaimType.CONFIGURATION_DEFAULT]
    assert [(c.subject, c.value, c.unit, c.table_cell, c.line) for c in cs] == [
        ("timeout", 30, "seconds", (0, 1), 3),
        ("retries", 3, None, (1, 1), 4),
    ]
    assert all(c.location_verified for c in cs)


def test_heading_identifier_claim() -> None:
    c = one("## create_client()\n\nText here.\n", ClaimType.IDENTIFIER_REFERENCE)
    assert c.subject == "create_client" and c.certainty == Certainty.HIGH
    c2 = one("## `create_client()`\n", ClaimType.IDENTIFIER_REFERENCE)
    assert c2.subject == "create_client"


@pytest.mark.parametrize(
    ("text", "value", "unit"),
    [
        ("The default timeout is 1,000 ms.", 1000, "milliseconds"),
        ("The default timeout is 1_000 s.", 1000, "seconds"),
        ("The default ratio is 0.5.", 0.5, None),
        ("The default timeout is 5 min.", 5, "minutes"),
        ("The default ttl is 2 hours.", 2, "hours"),
        ("The default ttl is 3d.", 3, "days"),
    ],
)
def test_numbers_and_units(text: str, value: float, unit: str | None) -> None:
    c = one(text, ClaimType.CONFIGURATION_DEFAULT)
    assert c.value == value and c.unit == unit


def test_negative_cases() -> None:
    assert claims_for("In 30 seconds you will see the result.") == []
    assert claims_for("```\nThe default timeout is 30 seconds.\n```\n") == []
    assert claims_for("Nothing interesting here.") == []


def test_stable_ids_and_determinism() -> None:
    text = "The default timeout is 30 seconds. Set MAX_RETRIES now.\n"
    a, b = claims_for(text), claims_for(text)
    assert a == b
    assert len({c.claim_id for c in a}) == len(a)
    assert subject_tokens("maxRetriesCount") == ("max", "retries", "count")
