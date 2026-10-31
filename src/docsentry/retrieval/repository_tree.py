import logging
from typing import Any

from docsentry.config import Settings
from docsentry.retrieval.classify import classify_path
from docsentry.retrieval.errors import translate_github_exception
from docsentry.retrieval.models import RepositoryFileEntry, RepositoryFileIndex

logger = logging.getLogger(__name__)


def build_repository_index(
    repo: Any,
    commit_sha: str,
    limits: Settings,
    tree_logger: logging.Logger | None = None,
) -> RepositoryFileIndex:
    """Build a file index for the repository at a specific commit SHA using Git Trees API."""
    log = tree_logger or logger
    try:
        tree = repo.get_git_tree(commit_sha, recursive=True)
    except Exception as exc:
        raise translate_github_exception(exc, "get_git_tree_root") from exc

    is_truncated = bool(getattr(tree, "truncated", False))

    if not is_truncated:
        entries: list[RepositoryFileEntry] = []
        seen: set[str] = set()
        for element in getattr(tree, "tree", []):
            el_type = getattr(element, "type", "")
            if el_type in ("blob", "commit"):
                raw_path = getattr(element, "path", "")
                norm_path = raw_path.replace("\\", "/").strip("/")
                if norm_path and norm_path not in seen:
                    seen.add(norm_path)
                    cat = classify_path(norm_path)
                    entry = RepositoryFileEntry(
                        path=norm_path,
                        type=el_type,
                        mode=getattr(element, "mode", "100644"),
                        blob_sha=getattr(element, "sha", "0" * 40),
                        size=getattr(element, "size", None),
                        commit_sha=commit_sha,
                        category=cat,
                    )
                    entries.append(entry)
        log.info("Built non-truncated tree index for %s with %d entries", commit_sha, len(entries))
        return RepositoryFileIndex(
            commit_sha=commit_sha,
            entries=entries,
            complete=True,
            truncated_recursive=False,
            incomplete_reasons=[],
        )

    # Truncated fallback: non-recursive subtree walk
    log.warning("Recursive tree truncated for %s; walking subtrees non-recursively", commit_sha)
    requests_budget = limits.max_tree_requests
    requests_used = 1
    entries_walk: list[RepositoryFileEntry] = []
    seen_walk: set[str] = set()
    incomplete_reasons: list[str] = []
    complete = True

    # Queue holds (path_prefix, subtree_sha)
    queue: list[tuple[str, str]] = [("", commit_sha)]

    while queue:
        if requests_used >= requests_budget:
            complete = False
            incomplete_reasons.append(f"max_tree_requests limit reached ({requests_budget})")
            break

        prefix, subtree_sha = queue.pop(0)
        try:
            subtree = repo.get_git_tree(subtree_sha, recursive=False)
            requests_used += 1
        except Exception as exc:
            complete = False
            incomplete_reasons.append(
                f"Subtree fetch failed for {prefix or 'root'}: {type(exc).__name__}"
            )
            break

        for el in getattr(subtree, "tree", []):
            el_type = getattr(el, "type", "")
            raw_name = getattr(el, "path", "")
            item_path = f"{prefix}/{raw_name}" if prefix else raw_name
            norm_path = item_path.replace("\\", "/").strip("/")
            if el_type == "tree":
                queue.append((norm_path, el.sha))
            elif el_type in ("blob", "commit"):
                if norm_path and norm_path not in seen_walk:
                    seen_walk.add(norm_path)
                    cat = classify_path(norm_path)
                    entries_walk.append(
                        RepositoryFileEntry(
                            path=norm_path,
                            type=el_type,
                            mode=getattr(el, "mode", "100644"),
                            blob_sha=getattr(el, "sha", "0" * 40),
                            size=getattr(el, "size", None),
                            commit_sha=commit_sha,
                            category=cat,
                        )
                    )

    return RepositoryFileIndex(
        commit_sha=commit_sha,
        entries=entries_walk,
        complete=complete,
        truncated_recursive=True,
        incomplete_reasons=incomplete_reasons,
    )
