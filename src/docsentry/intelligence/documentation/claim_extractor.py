"""Deterministic, rule-based claim extraction from parsed documentation."""

import hashlib
import re
from collections import Counter

from docsentry.intelligence.models.common import Certainty
from docsentry.intelligence.models.documentation import (
    ClaimType,
    DocClaim,
    DocStatement,
    DocTable,
    ParsedDocument,
)

UNIT_LABELS = {
    "ms": "milliseconds",
    "millisecond": "milliseconds",
    "milliseconds": "milliseconds",
    "s": "seconds",
    "sec": "seconds",
    "secs": "seconds",
    "second": "seconds",
    "seconds": "seconds",
    "min": "minutes",
    "mins": "minutes",
    "minute": "minutes",
    "minutes": "minutes",
    "h": "hours",
    "hour": "hours",
    "hours": "hours",
    "d": "days",
    "day": "days",
    "days": "days",
}
UNIT_SECONDS = {
    "milliseconds": 0.001,
    "seconds": 1.0,
    "minutes": 60.0,
    "hours": 3600.0,
    "days": 86400.0,
}
HINT_TO_LABEL = {"ms": "milliseconds", "s": "seconds", "min": "minutes", "h": "hours", "d": "days"}

_NUM = (
    r"(?P<num>[-+]?(?:\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:_\d+)*(?:\.\d+)?)"
    r"(?:[eE][-+]?\d+)?)"
)
_UNIT = r"(?:\s*(?P<unit>milliseconds?|seconds?|secs?|minutes?|mins?|hours?|days?|ms|h|d|s)\b)?"
_VALUE = _NUM + _UNIT
_SUBJ_TICK = r"`(?P<tick>[A-Za-z_][\w.]*)`"
_IDENT = r"[A-Za-z_]\w*"

_KIND = r"(?:parameter|option|setting|argument|arg|variable|flag|key|field|attribute|property)"
_R_CODE_DEFAULT = re.compile(
    _SUBJ_TICK
    + r"(?:\s+"
    + _KIND
    + r")?\s+(?:defaults?\s+to|is\s+set\s+to\s+default|is\s+by\s+default|has\s+a\s+default"
    r"(?:\s+value)?\s+of)\s+`?" + _VALUE,
    re.IGNORECASE,
)
_R_DEFAULT_OF = re.compile(
    r"\bdefault(?:\s+value)?\s+(?:of|for)\s+(?:the\s+)?`?(?P<name>" + _IDENT + r")`?"
    r"(?:\s+(?:option|setting|parameter|variable))?\s+(?:is|=|:)\s+`?" + _VALUE,
    re.IGNORECASE,
)
_R_DEFAULT_IS = re.compile(
    r"\bdefault\s+(?!value\b)(?P<name>`?" + _IDENT + r"`?(?:\s+" + _IDENT + r"){0,2}?)"
    r"\s+(?:is|=|are)\s+`?" + _VALUE,
    re.IGNORECASE,
)
_R_NAME_KIND_DEFAULTS = re.compile(
    r"(?<![`\w])(?P<name>" + _IDENT + r")\s+" + _KIND + r"\s+defaults?\s+to\s+`?" + _VALUE,
    re.IGNORECASE,
)
_GENERIC_KINDS = {
    "parameter", "option", "setting", "argument", "arg", "variable", "flag", "key", "field",
    "attribute", "property", "value", "it", "this", "which",
}  # fmt: skip
_R_INHERITED_DEFAULT = re.compile(
    r"^\s*(?:it\s+|which\s+)?(?:defaults?\s+to|the\s+default(?:\s+value)?\s+is|default(?:\s+value)?\s*[:=]|"
    r"default\s+is)\s+`?" + _VALUE,
    re.IGNORECASE,
)
_R_LEAD_SUBJECT = re.compile(
    r"^\s*(?:[-*+]\s+)?(?:`(?P<t>[-]{0,2}[A-Za-z_][\w.\-]*)`|(?P<u>[A-Za-z_][\w.]*))\s*(?::|\u2014|\u2013|\s-\s)"
)
_R_NAME_DEFAULTS_TO = re.compile(
    r"(?<![`\w])(?P<name>" + _IDENT + r")\s+defaults?\s+to\s+`?" + _VALUE,
    re.IGNORECASE,
)
_R_SIGNATURE = re.compile(r"`(?P<fn>[A-Za-z_][\w.]*)\((?P<args>[^`()]*)\)`")
_R_BARE_CALL = re.compile(r"(?<![\w`.])(?P<fn>[A-Za-z_]\w*)\(\)")
_R_PARAM = re.compile(
    r"`(?P<p1>" + _IDENT + r")`\s+(?:parameter|argument|option|kwarg|keyword)\b"
    r"|\b(?:parameter|argument)\s+`(?P<p2>" + _IDENT + r")`",
    re.IGNORECASE,
)
_R_TICKED = re.compile(r"`(?P<t>[^`\n]+)`")
_R_HTTP = re.compile(
    r"\b(?P<m>GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS|TRACE|CONNECT)\s+(?:request|call|endpoint|method)s?\b"
    r"|\b(?:HTTP|method)\s+(?P<m2>GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS|TRACE|CONNECT)\b"
)
_R_RETURN = re.compile(r"\breturns?\s+(?:an?\s+|the\s+)?`(?P<t>[^`\n]+)`", re.IGNORECASE)
_R_VERSION = re.compile(
    r"\bPython\s+(?P<v>\d+\.\d+)(?:\.\d+)?(?P<newer>\s+or\s+(?:newer|later|higher|above))?",
    re.IGNORECASE,
)
_R_CONFIG_TOKEN = re.compile(r"(?<![\w])[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+(?![\w])")
_R_CAPS_TICKED = re.compile(r"`([A-Z][A-Z0-9_]{2,})`")
_R_BEHAVIOR = re.compile(
    r"\b(?:retr(?:y|ies|ied)|caches?|cached|validates?|logs?|raises?|sends?|checks?|falls? back"
    r"|times? out|rejects?|deduplicates?|sanitizes?|normalizes?|encrypts?|compress(?:es)?"
    r"|batches|throttles?|blocks?|queues?|schedules?|resolves?|refreshes?|waits?|skips?)\b",
    re.IGNORECASE,
)

_STOP = {"the", "a", "an", "default", "value", "of", "is", "for", "option", "setting"}
_NAME_HEADERS = {
    "option", "parameter", "key", "setting", "name", "variable", "env", "argument", "flag",
    "parameter name", "option name", "setting name", "variable name", "argument name",
    "key name", "config", "config key", "config option", "configuration", "field", "property",
    "environment variable", "env var", "cli flag", "flag name", "arg", "attribute",
}  # fmt: skip
_DEFAULT_HEADERS = {
    "default", "default value", "default_value", "defaults", "default setting", "default val",
    "default (value)", "value (default)",
}  # fmt: skip
_CAMEL = re.compile(r"[A-Z]?[a-z0-9]+|[A-Z]+(?![a-z])")
_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS", "TRACE", "CONNECT"}
_PY_BUILTINS = {
    "int", "str", "float", "bool", "list", "dict", "set", "tuple", "None", "True", "False",
    "bytes", "object", "type", "self", "cls",
}  # fmt: skip


def subject_tokens(subject: str | None) -> tuple[str, ...]:
    if not subject:
        return ()
    tokens: list[str] = []
    for part in re.split(r"[_\s.\-/]+", subject.strip("`")):
        for piece in _CAMEL.findall(part):
            low = piece.lower()
            if low and low not in _STOP:
                tokens.append(low)
    return tuple(tokens)


def parse_number(raw: str) -> int | float:
    cleaned = raw.replace(",", "").replace("_", "")
    if "." in cleaned or "e" in cleaned.lower():
        return float(cleaned)
    return int(cleaned)


def normalize_unit(raw: str | None) -> str | None:
    if raw is None:
        return None
    return UNIT_LABELS.get(raw.lower())


def _claim_id(
    path: str, statement_id: str, ctype: ClaimType, subject: str | None, method: str, occ: int
) -> str:
    raw = "|".join([path, statement_id, ctype.value, subject or "", method, str(occ)])
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


class _Builder:
    def __init__(self, doc: ParsedDocument) -> None:
        self.doc = doc
        self.claims: list[DocClaim] = []
        self._occ: Counter[tuple[str, ClaimType, str, str]] = Counter()

    def add(
        self,
        st: DocStatement,
        ctype: ClaimType,
        method: str,
        certainty: Certainty,
        *,
        subject: str | None = None,
        value: object = None,
        unit: str | None = None,
        parameters: tuple[str, ...] = (),
        original_text: str | None = None,
        line: int | None = None,
        verified: bool | None = None,
        table_cell: tuple[int, int] | None = None,
    ) -> None:
        key = (st.statement_id, ctype, subject or "", method)
        occ = self._occ[key]
        self._occ[key] += 1
        ok = st.location_verified if verified is None else verified
        self.claims.append(
            DocClaim(
                claim_id=_claim_id(self.doc.path, st.statement_id, ctype, subject, method, occ),
                claim_type=ctype,
                subject=subject,
                subject_tokens=subject_tokens(subject),
                value=value,
                unit=unit,
                parameters=parameters,
                original_text=original_text if original_text is not None else st.text,
                path=self.doc.path,
                line=line if line is not None else st.line,
                column=st.column if ok else None,
                end_line=st.end_line,
                statement_id=st.statement_id,
                heading_path=st.heading_path,
                extraction_method=method,
                certainty=certainty,
                location_verified=ok,
                table_cell=table_cell,
            )
        )


def _value_of(m: re.Match[str]) -> tuple[int | float, str | None]:
    return parse_number(m.group("num")), normalize_unit(m.group("unit"))


def _params(args: str) -> tuple[str, ...]:
    out: list[str] = []
    for raw in args.split(","):
        item = raw.strip().split("=")[0].split(":")[0].strip().lstrip("*")
        if re.fullmatch(_IDENT, item) and item not in {"self", "cls"}:
            out.append(item)
    return tuple(out)


def _statement_claims(b: _Builder, st: DocStatement, is_heading: bool) -> None:
    text = st.text
    before = len(b.claims)
    default_spans: list[tuple[int, int]] = []

    if not is_heading:
        for m in _R_CODE_DEFAULT.finditer(text):
            v, u = _value_of(m)
            b.add(
                st, ClaimType.CONFIGURATION_DEFAULT, "cfg_default_code_ident", Certainty.HIGH,
                subject=m.group("tick"), value=v, unit=u,
            )  # fmt: skip
            default_spans.append(m.span())
        for m in _R_DEFAULT_OF.finditer(text):
            v, u = _value_of(m)
            ticked = f"`{m.group('name')}`" in text
            b.add(
                st, ClaimType.CONFIGURATION_DEFAULT, "cfg_default_of",
                Certainty.HIGH if ticked else Certainty.MEDIUM,
                subject=m.group("name"), value=v, unit=u,
            )  # fmt: skip
            default_spans.append(m.span())
        for m in _R_DEFAULT_IS.finditer(text):
            if any(s <= m.start() < e for s, e in default_spans):
                continue
            v, u = _value_of(m)
            name = m.group("name").strip("`")
            b.add(
                st, ClaimType.CONFIGURATION_DEFAULT, "cfg_default_is", Certainty.MEDIUM,
                subject=name, value=v, unit=u,
            )  # fmt: skip
            default_spans.append(m.span())
        for m in _R_NAME_KIND_DEFAULTS.finditer(text):
            if any(s <= m.start() < e for s, e in default_spans):
                continue
            if m.group("name").lower() in _GENERIC_KINDS:
                continue
            v, u = _value_of(m)
            b.add(
                st, ClaimType.CONFIGURATION_DEFAULT, "cfg_default_named_kind", Certainty.MEDIUM,
                subject=m.group("name"), value=v, unit=u,
            )  # fmt: skip
            default_spans.append(m.span())
        for m in _R_NAME_DEFAULTS_TO.finditer(text):
            if any(s <= m.start() < e or m.start() <= s < m.end() for s, e in default_spans):
                continue
            if m.group("name").lower() in _GENERIC_KINDS:
                continue
            v, u = _value_of(m)
            b.add(
                st, ClaimType.CONFIGURATION_DEFAULT, "cfg_name_defaults_to", Certainty.MEDIUM,
                subject=m.group("name"), value=v, unit=u,
            )  # fmt: skip

    sig_spans: list[tuple[int, int]] = []
    for m in _R_SIGNATURE.finditer(text):
        fn = m.group("fn")
        params = _params(m.group("args"))
        sig_spans.append(m.span())
        if is_heading or not params:
            b.add(
                st, ClaimType.IDENTIFIER_REFERENCE, "ident_call_form", Certainty.HIGH,
                subject=fn.split(".")[-1], original_text=st.text,
            )  # fmt: skip
        else:
            b.add(
                st, ClaimType.API_SIGNATURE, "api_signature_code", Certainty.HIGH,
                subject=fn.split(".")[-1], parameters=params,
            )  # fmt: skip
    if is_heading:
        for m in _R_BARE_CALL.finditer(text):
            b.add(
                st, ClaimType.IDENTIFIER_REFERENCE, "ident_heading_call", Certainty.HIGH,
                subject=m.group("fn"),
            )  # fmt: skip

    param_names: set[str] = set()
    for m in _R_PARAM.finditer(text):
        name = m.group("p1") or m.group("p2")
        param_names.add(name)
        b.add(st, ClaimType.PARAMETER_MENTION, "param_mention", Certainty.HIGH, subject=name)

    seen_refs: set[str] = {c.subject for c in b.claims[before:] if c.subject}
    for m in _R_CAPS_TICKED.finditer(text):
        name = m.group(1)
        if name in _METHODS and not is_heading:
            continue
        if name in seen_refs and not is_heading:
            continue
        seen_refs.add(name)
        b.add(st, ClaimType.CONFIGURATION_REFERENCE, "cfg_ref_ticked", Certainty.HIGH, subject=name)
    if not is_heading:
        for m in _R_CONFIG_TOKEN.finditer(text):
            name = m.group(0)
            if name in seen_refs:
                continue
            seen_refs.add(name)
            b.add(
                st, ClaimType.CONFIGURATION_REFERENCE, "cfg_ref_token", Certainty.MEDIUM,
                subject=name,
            )  # fmt: skip
    for m in _R_TICKED.finditer(text):
        token = m.group("t").strip()
        bare = token[:-2] if token.endswith("()") else token
        if (
            bare in seen_refs
            or bare in param_names
            or bare in _PY_BUILTINS
            or not re.fullmatch(r"[A-Za-z_][\w.]*", bare)
        ):
            continue
        last = bare.split(".")[-1]
        is_call = token.endswith("()")
        snake = "_" in last and last == last.lower()
        camel = last[:1].isupper() and not last.isupper()
        if not (is_call or snake or camel or (is_heading and last == last.lower())):
            continue
        if last.isupper() or last in seen_refs:
            continue
        if any(s <= m.start() < e for s, e in sig_spans):
            continue
        seen_refs.add(last)
        b.add(st, ClaimType.IDENTIFIER_REFERENCE, "ident_ticked", Certainty.HIGH, subject=last)

    if is_heading:
        return

    for m in _R_HTTP.finditer(text):
        method = m.group("m") or m.group("m2")
        b.add(
            st, ClaimType.HTTP_METHOD, "http_method", Certainty.MEDIUM,
            subject=method, value=method,
        )  # fmt: skip
    for m in _R_RETURN.finditer(text):
        rtype = m.group("t")
        b.add(st, ClaimType.RETURN_TYPE, "return_type_ticked", Certainty.MEDIUM, value=rtype)
    for m in _R_VERSION.finditer(text):
        b.add(
            st, ClaimType.VERSION_STATEMENT, "version_python",
            Certainty.HIGH if m.group("newer") else Certainty.MEDIUM,
            subject="python", value=m.group("v"),
        )  # fmt: skip

    if len(b.claims) == before and _R_BEHAVIOR.search(text):
        b.add(st, ClaimType.BEHAVIORAL_CANDIDATE, "behavioral_verb", Certainty.LOW)


def _table_claims(b: _Builder, table: DocTable, row_statements: dict[int, DocStatement]) -> None:
    header = [h.strip().strip("`").lower() for h in table.header]
    name_col = next((i for i, h in enumerate(header) if h in _NAME_HEADERS), None)
    default_col = next((i for i, h in enumerate(header) if h in _DEFAULT_HEADERS), None)
    if name_col is None or default_col is None:
        return
    for row in table.rows:
        if len(row) <= max(name_col, default_col):
            continue
        name_cell, default_cell = row[name_col], row[default_col]
        st = row_statements.get(default_cell.line)
        if st is None:
            continue
        subject = name_cell.text.strip().strip("`").strip().lstrip("-")
        if not re.fullmatch(r"[A-Za-z_][\w.\-]*", subject):
            continue
        m = re.fullmatch(r"`?" + _VALUE + r"`?", default_cell.text.strip())
        if not m:
            continue
        v, u = _value_of(m)
        ticked = name_cell.text.strip().startswith("`")
        b.add(
            st, ClaimType.CONFIGURATION_DEFAULT, "cfg_default_table",
            Certainty.HIGH if ticked else Certainty.MEDIUM,
            subject=subject, value=v, unit=u,
            original_text=f"{name_cell.text} | {default_cell.text}",
            line=default_cell.line, verified=default_cell.line_verified and st.location_verified,
            table_cell=(default_cell.row, default_cell.col),
        )  # fmt: skip


_HISTORY_EXACT = {"changes", "history", "news", "releases"}
_HISTORY_PREFIX = (
    "changelog", "change-log", "release-notes", "releasenotes", "release_notes",
    "whatsnew", "whats-new", "whats_new",
)  # fmt: skip


def is_history_doc(path: str) -> bool:
    """Changelog-style files describe past behaviour on purpose; never treat them as live docs."""
    parts = path.lower().replace("\\", "/").split("/")
    stem = parts[-1].rsplit(".", 1)[0]
    if stem in _HISTORY_EXACT or any(stem.startswith(p) for p in _HISTORY_PREFIX):
        return True
    return any(p in ("changelog", "release-notes", "releases", "history") for p in parts[:-1])


_R_COLON_SUBJECT = re.compile(r"(?:^|\s)(?P<u>[A-Za-z_]\w*)\s*:\s")


def _lead_subject(text: str) -> str | None:
    m = _R_LEAD_SUBJECT.match(text)
    if m:
        name = (m.group("t") or m.group("u") or "").lstrip("-")
        return name if re.fullmatch(r"[A-Za-z_][\w.\-]*", name) else None
    # soft-wrapped lines ("Options NAME: text"): accept only constant-style or snake_case names
    c = _R_COLON_SUBJECT.search(text[:80])
    if c:
        name = c.group("u")
        if name.isupper() or "_" in name:
            return name
    return None


def extract_claims(doc: ParsedDocument) -> list[DocClaim]:
    if is_history_doc(doc.path):
        return []
    b = _Builder(doc)
    block_kind = {blk.block_id: blk.kind for blk in doc.blocks}
    row_statements: dict[int, DocStatement] = {}
    last_subject: dict[str, str] = {}
    for st in doc.statements:
        kind = block_kind.get(st.block_id)
        if kind == "table_row":
            row_statements[st.line] = st
            continue
        _statement_claims(b, st, kind == "heading")
        if kind != "heading":
            subject = last_subject.get(st.block_id)
            m = _R_INHERITED_DEFAULT.match(st.text)
            if (
                subject
                and m
                and not any(
                    c.statement_id == st.statement_id
                    and c.claim_type == ClaimType.CONFIGURATION_DEFAULT
                    for c in b.claims
                )
            ):
                v, u = _value_of(m)
                b.add(
                    st, ClaimType.CONFIGURATION_DEFAULT, "cfg_default_inherited", Certainty.MEDIUM,
                    subject=subject, value=v, unit=u,
                )  # fmt: skip
            lead = _lead_subject(st.text)
            if lead:
                last_subject[st.block_id] = lead
    for table in doc.tables:
        _table_claims(b, table, row_statements)
    return sorted(b.claims, key=lambda c: (c.line, c.statement_id, c.extraction_method, c.claim_id))
