"""AI orchestration. Fail-open: never alters Stage 3 results, never calls GitHub."""

import asyncio
import time
from collections.abc import Callable
from typing import Protocol

from docsentry.ai_review.evidence import build_batches
from docsentry.ai_review.models import (
    PROMPT_VERSION,
    AIItemAssessment,
    AIReviewResult,
    AIReviewStatus,
)
from docsentry.ai_review.ollama import LlamaCppClient, OllamaClient, OllamaError
from docsentry.ai_review.prompts import build_messages, schema
from docsentry.ai_review.validator import ValidationFailure, validate_batch
from docsentry.config import Settings
from docsentry.intelligence.models.analysis import AnalysisResult

_TRANSIENT = {"ollama_unreachable", "ollama_timeout"}


class AIReviewer(Protocol):
    async def review(self, result: AnalysisResult) -> AIReviewResult: ...


class NullAIReviewer:
    """Default seam: AI disabled, zero Ollama requests."""

    async def review(self, result: AnalysisResult) -> AIReviewResult:
        return AIReviewResult(status=AIReviewStatus.SKIPPED_DISABLED)


class OllamaAIReviewer:
    def __init__(
        self,
        settings: Settings,
        client: OllamaClient | None = None,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._s = settings
        self._client = client
        self._mono = monotonic
        self._sem = asyncio.Semaphore(1)  # model concurrency is a constant of 1

    def _result(
        self,
        status: AIReviewStatus,
        t0: float,
        code: str | None = None,
        assessments: tuple[AIItemAssessment, ...] = (),
        batches: int = 0,
        items_total: int = 0,
    ) -> AIReviewResult:
        return AIReviewResult(
            status=status,
            assessments=assessments,
            model=self._s.ollama_model,
            prompt_version=PROMPT_VERSION,
            error_code=code,
            batches=batches,
            items_total=items_total,
            items_reviewed=len(assessments),
            elapsed_ms=int((self._mono() - t0) * 1000),
        )

    async def review(self, result: AnalysisResult) -> AIReviewResult:
        t0 = self._mono()
        s = self._s
        if not s.ai_effective:
            return AIReviewResult(status=AIReviewStatus.SKIPPED_DISABLED)
        inp = result.ai_review_input
        if not inp.items:
            return self._result(AIReviewStatus.SKIPPED_NO_ITEMS, t0)
        total = len(inp.items)
        if not result.complete or not inp.complete:
            return self._result(AIReviewStatus.SKIPPED_INCOMPLETE_INPUT, t0, items_total=total)
        batches, dropped = build_batches(
            result, s.ai_review_max_batch_items, s.ai_review_max_batch_chars
        )
        cls = LlamaCppClient if s.ai_backend == "llama_cpp" else OllamaClient
        client = self._client or cls(s.ollama_base_url, s.ollama_timeout_seconds)
        done: list[AIItemAssessment] = []
        failures: list[str] = []
        ran = 0
        async with self._sem:
            for batch in batches:
                if self._mono() - t0 >= s.ai_review_total_budget_seconds:
                    failures.append("ai_budget_exceeded")
                    break
                ran += 1
                attempts = 0
                while True:
                    try:
                        raw = await asyncio.to_thread(
                            client.chat,
                            s.ollama_model,
                            build_messages(batch),
                            schema(),
                            s.ollama_num_ctx,
                            s.ai_review_max_output_tokens,
                        )
                        done.extend(validate_batch(raw, batch))
                        break
                    except OllamaError as exc:
                        retry = (
                            exc.code in _TRANSIENT
                            and attempts < s.ai_review_max_retries
                            and self._mono() - t0 < s.ai_review_total_budget_seconds
                        )
                        if retry:
                            attempts += 1
                            continue
                        failures.append(exc.code)
                        break
                    except ValidationFailure as exc:
                        failures.append(exc.code)  # never retry invalid model output
                        break
        if not failures and not dropped and len(done) == total:
            return self._result(AIReviewStatus.COMPLETED, t0, None, tuple(done), ran, total)
        if done:
            code = failures[0] if failures else "ai_items_unreviewed"
            return self._result(AIReviewStatus.PARTIAL, t0, code, tuple(done), ran, total)
        code = failures[0] if failures else "ai_no_assessments"
        if code == "ai_budget_exceeded":
            status = AIReviewStatus.FAILED
        elif code.startswith("ollama_"):
            status = AIReviewStatus.UNAVAILABLE
        else:
            status = AIReviewStatus.INVALID_OUTPUT
        return self._result(status, t0, code, (), ran, total)
