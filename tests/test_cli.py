from pathlib import Path

import pytest

from careerbrain.adapters.cli import OfflineLLM, main, run
from careerbrain.bootstrap import open_brain
from careerbrain.core.engine import Engine
from careerbrain.core.memory import Message
from careerbrain.core.ratelimit import CooldownLimiter


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def brain_root(tmp_path: Path) -> Path:
    (tmp_path / "brain.config.yaml").write_text("paths: {}\n", encoding="utf-8")
    (tmp_path / "projects").mkdir()
    (tmp_path / "projects/etl.md").write_text(
        "---\ntype: project\npublic: true\n---\n\n# ETL\n\n## Airflow helper\n\n"
        "Built an agent that triages Airflow failures.\n",
        encoding="utf-8",
    )
    return tmp_path


def _scripted(lines: list[str]):
    queue = list(lines)

    def read(prompt: str) -> str:
        if not queue:
            raise EOFError
        return queue.pop(0)

    return read


def _engine(root: Path, clock: FakeClock | None = None) -> Engine:
    return Engine(
        retriever=open_brain(root),
        llm=OfflineLLM(),
        limiter=CooldownLimiter(10.0, clock=clock or FakeClock()),
    )


def test_run_answers_questions_and_exits_on_quit(brain_root: Path) -> None:
    output: list[str] = []
    run(_engine(brain_root), _scripted(["airflow", "/quit", "never"]), output.append)

    assert len(output) == 1
    assert "- projects/etl.md" in output[0]
    assert "(sources: projects/etl.md)" in output[0]


def test_run_reports_reset(brain_root: Path) -> None:
    output: list[str] = []
    run(_engine(brain_root), _scripted(["/reset", "/exit"]), output.append)
    assert output == ["History cleared."]


def test_run_skips_blank_lines(brain_root: Path) -> None:
    output: list[str] = []
    run(_engine(brain_root), _scripted(["   ", "", "/quit"]), output.append)
    assert output == []


def test_run_reports_rate_limit(brain_root: Path) -> None:
    clock = FakeClock()
    output: list[str] = []
    run(
        _engine(brain_root, clock),
        _scripted(["airflow", "airflow again", "/quit"]),
        output.append,
    )
    assert output[1] == "Too fast. Try again in 10.0s."


def test_run_exits_cleanly_on_eof(brain_root: Path) -> None:
    output: list[str] = []
    run(_engine(brain_root), _scripted([]), output.append)
    assert output == [""]


def test_offline_llm_lists_pages_from_system_context() -> None:
    reply = OfflineLLM().complete(
        [
            Message(
                "system",
                "Context:\n\n[source: projects/a.md]\n## Heading\nbody\n\n"
                "[source: projects/b.md]\nbody",
            ),
            Message("user", "q"),
        ]
    )
    assert "- projects/a.md" in reply
    assert "- projects/b.md" in reply


def test_main_offline_runs_without_api_key(
    brain_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.setattr("builtins.input", lambda _prompt: "/quit")

    assert main(["--offline", "--root", str(brain_root)]) == 0
    assert "Career Brain CLI" in capsys.readouterr().out


def test_main_requires_api_key_without_offline(
    brain_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv("GROQ_API_KEY", raising=False)

    assert main(["--root", str(brain_root)]) == 1
    assert "GROQ_API_KEY" in capsys.readouterr().err


def test_main_reports_missing_brain(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("CAREERBRAIN_ROOT", raising=False)
    assert main(["--offline", "--root", str(tmp_path / "missing")]) == 1
    assert "brain.config.yaml" in capsys.readouterr().err


def test_run_reports_llm_errors_without_crashing(brain_root: Path) -> None:
    from careerbrain.core.llm import LLMError

    class FailingLLM:
        def complete(self, messages):
            raise LLMError("model unavailable")

    engine = Engine(
        retriever=open_brain(brain_root),
        llm=FailingLLM(),
        limiter=CooldownLimiter(10.0, clock=FakeClock()),
    )
    output: list[str] = []
    run(engine, _scripted(["airflow", "/quit"]), output.append)
    assert output == ["Language model error: model unavailable"]
