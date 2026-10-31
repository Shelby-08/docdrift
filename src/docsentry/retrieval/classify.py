from pathlib import PurePosixPath
from typing import Literal

Category = Literal["source", "doc", "config", "other"]

DOC_EXTENSIONS = frozenset({".md", ".mdx", ".markdown", ".rst", ".adoc"})
DOC_BASENAMES = frozenset({"README", "CHANGELOG", "CONTRIBUTING"})
SOURCE_EXTENSIONS = frozenset(
    {
        ".py",
        ".ts",
        ".tsx",
        ".js",
        ".jsx",
        ".mjs",
        ".cjs",
        ".go",
        ".java",
        ".rs",
        ".rb",
        ".php",
        ".cs",
        ".kt",
        ".swift",
        ".c",
        ".h",
        ".cpp",
    }
)
CONFIG_EXTENSIONS = frozenset({".json", ".yaml", ".yml", ".toml", ".ini", ".cfg"})
IGNORED_SEGMENTS = frozenset({"node_modules", "vendor", ".git", "dist", "build", ".venv"})


def classify_path(path: str) -> Category:
    """Classify a file path into source, doc, config, or other."""
    clean_path = path.replace("\\", "/").strip()
    while clean_path.startswith("./"):
        clean_path = clean_path[2:]

    posix = PurePosixPath(clean_path)
    for part in posix.parts:
        if part in IGNORED_SEGMENTS:
            return "other"

    suffix = posix.suffix.lower()
    stem_upper = posix.stem.upper()

    if suffix in DOC_EXTENSIONS or stem_upper in DOC_BASENAMES:
        return "doc"

    if suffix in SOURCE_EXTENSIONS:
        return "source"

    if suffix in CONFIG_EXTENSIONS:
        return "config"

    return "other"
