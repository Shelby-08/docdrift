from typing import Any

import pytest

import docsentry.__main__ as entry
from docsentry.app import create_app
from docsentry.config import Settings


def settings() -> Settings:
    return Settings(github_app_id="1", github_private_key="k", github_webhook_secret="s")


def test_main_wires_the_real_pipeline_not_the_log_only_handler(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, Any] = {}

    def fake_create_app(s: Settings, handler: Any = None, logger: Any = None) -> Any:
        seen["handler"] = handler
        return create_app(s, handler, logger)

    monkeypatch.setattr(entry, "load_settings", settings)
    monkeypatch.setattr(entry, "create_app", fake_create_app)
    monkeypatch.setattr(entry.uvicorn, "run", lambda *a, **k: None)
    entry.main()
    assert seen["handler"] is None  # None => JobManager.submit (analysis + Check Run)


def test_default_app_dispatches_to_job_manager(monkeypatch: pytest.MonkeyPatch) -> None:
    import docsentry.app as app_mod

    created: list[Any] = []
    real = app_mod.JobManager

    class Spy(real):  # type: ignore[valid-type, misc]
        def __init__(self, *a: Any, **k: Any) -> None:
            super().__init__(*a, **k)
            created.append(k)

    monkeypatch.setattr(app_mod, "JobManager", Spy)
    create_app(settings(), None)
    assert created and created[0]["analyzer"] is not None and created[0]["publisher"] is not None
