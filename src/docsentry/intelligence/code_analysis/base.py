from typing import Protocol

from docsentry.intelligence.models.code import ParsedSource


class LanguageAdapter(Protocol):
    language: str
    extensions: tuple[str, ...]

    def parse(self, path: str, text: str, commit_sha: str) -> ParsedSource: ...
