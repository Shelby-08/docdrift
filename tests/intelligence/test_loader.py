from docsentry.intelligence.models.common import AnalysisLimits
from docsentry.intelligence.repository.loader import load_snapshots
from tests.intelligence.bundles import HEAD, MERGE_BASE, make_bundle

LIMITS = AnalysisLimits()
DOC = "# Config\n\nThe default timeout is 30 seconds.\n"


def test_unchanged_doc_discovered_via_index_and_loaded_once() -> None:
    base = {"src/config.py": "DEFAULT_TIMEOUT = 30\n", "docs/configuration.md": DOC}
    head = {"src/config.py": "DEFAULT_TIMEOUT = 60\n", "docs/configuration.md": DOC}
    bundle, src = make_bundle(base, head)
    b, h = load_snapshots(bundle, src, LIMITS)
    assert h.files["docs/configuration.md"] == DOC and b.files["docs/configuration.md"] == DOC
    doc_reads = [r for r in src.reads if r[0] == "docs/configuration.md"]
    assert len(doc_reads) == 1 and doc_reads[0][1] == HEAD


def test_reuses_bundle_snapshots_without_refetch() -> None:
    base = {"src/config.py": "DEFAULT_TIMEOUT = 30\n"}
    head = {"src/config.py": "DEFAULT_TIMEOUT = 60\n"}
    bundle, src = make_bundle(base, head)
    b, h = load_snapshots(bundle, src, LIMITS)
    assert src.reads == []
    assert b.files["src/config.py"] == base["src/config.py"]
    assert h.files["src/config.py"] == head["src/config.py"]


def test_merge_base_sha_used_for_base_reads() -> None:
    base = {"src/config.py": "DEFAULT_TIMEOUT = 30\n"}
    head = {"src/config.py": "DEFAULT_TIMEOUT = 60\n"}
    bundle, src = make_bundle(base, head, seed_snapshots=False)
    b, h = load_snapshots(bundle, src, LIMITS)
    assert b.commit_sha == MERGE_BASE and h.commit_sha == HEAD
    assert ("src/config.py", MERGE_BASE) in src.reads and ("src/config.py", HEAD) in src.reads
    assert all(sha in (MERGE_BASE, HEAD) for _, sha in src.reads)


def test_differing_blob_fetches_each_side() -> None:
    base = {"src/a.py": "A = 1\n", "docs/x.md": "# X\n\nOld text.\n"}
    head = {"src/a.py": "A = 2\n", "docs/x.md": "# X\n\nNew text.\n"}
    bundle, src = make_bundle(base, head, seed_snapshots=False)
    b, h = load_snapshots(bundle, src, LIMITS)
    assert b.files["docs/x.md"].endswith("Old text.\n") and h.files["docs/x.md"].endswith(
        "New text.\n"
    )


def test_skip_reasons_recorded_and_complete_false() -> None:
    base = {"src/a.py": "A = 1\n", "src/big.py": "B = 1\n", "web/app.ts": "export const x = 1;\n"}
    head = {"src/a.py": "A = 2\n", "src/big.py": "B = 2\n", "web/app.ts": "export const x = 2;\n"}
    bundle, src = make_bundle(base, head, seed_snapshots=False)
    src.oversized.add("src/big.py")
    b, h = load_snapshots(bundle, src, LIMITS)
    reasons = {(s.path, s.reason) for s in h.skipped}
    assert ("src/big.py", "oversized") in reasons
    assert ("web/app.ts", "unsupported_language") in reasons
    assert h.complete is False and b.complete is False


def test_test_files_recorded_but_do_not_reduce_completeness() -> None:
    base = {"src/a.py": "A = 1\n"}
    head = {"src/a.py": "A = 2\n", "tests/test_a.py": "def test_a():\n    pass\n"}
    bundle, src = make_bundle(base, head)
    _, h = load_snapshots(bundle, src, LIMITS)
    assert any(s.reason == "test_file" for s in h.skipped)
    assert h.complete is True


def test_incomplete_bundle_marks_snapshots_incomplete() -> None:
    bundle, src = make_bundle({"a.py": "A = 1\n"}, {"a.py": "A = 2\n"}, index_complete=False)
    b, h = load_snapshots(bundle, src, LIMITS)
    assert not b.complete and not h.complete
    assert "head_index_incomplete" in h.incomplete_reasons
    bundle2, src2 = make_bundle({"a.py": "A = 1\n"}, {"a.py": "A = 2\n"}, merge_base=None)
    _, h2 = load_snapshots(bundle2, src2, LIMITS)
    assert "merge_base_unresolved" in h2.incomplete_reasons


def test_doc_cap_respected_with_over_budget_recorded() -> None:
    docs = {f"docs/d{i}.md": f"# D{i}\n\nText {i}.\n" for i in range(5)}
    base = {"src/a.py": "A = 1\n", **docs}
    head = {"src/a.py": "A = 2\n", **docs}
    bundle, src = make_bundle(base, head, seed_snapshots=False)
    _, h = load_snapshots(bundle, src, AnalysisLimits(max_doc_files=2))
    assert sum(1 for p in h.files if p.endswith(".md")) == 2
    assert sum(1 for s in h.skipped if s.reason == "over_budget") == 3


def test_unchanged_source_cap_and_scan_incomplete() -> None:
    srcs = {f"src/m{i}.py": f"X{i} = {i}\n" for i in range(4)}
    base = {"src/a.py": "A = 1\n", **srcs}
    head = {"src/a.py": "A = 2\n", **srcs}
    bundle, src = make_bundle(base, head, seed_snapshots=False)
    _, h = load_snapshots(bundle, src, AnalysisLimits(max_unchanged_source_files=2))
    assert h.source_scan_complete is False
    assert len([p for p in h.files if p.startswith("src/m")]) == 2
    assert set(h.paths) >= set(head)


def test_time_budget_stops_loading() -> None:
    base = {"src/a.py": "A = 1\n", "docs/x.md": "# X\n"}
    head = {"src/a.py": "A = 2\n", "docs/x.md": "# X\n"}
    bundle, src = make_bundle(base, head, seed_snapshots=False)
    ticks = iter(range(0, 1000, 100))
    _, h = load_snapshots(
        bundle, src, AnalysisLimits(time_budget_seconds=1), lambda: float(next(ticks))
    )
    assert "time_budget" in h.incomplete_reasons
    assert any(s.reason == "time_budget" for s in h.skipped)
