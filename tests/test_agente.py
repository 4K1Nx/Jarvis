import importlib.util
import json
from pathlib import Path

import pytest

from viv.bus import BUS
from viv.tools import agente, code
from viv.tools.registry import Context, is_dangerous

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("agente_runner", ROOT / "scripts" / "agente_runner.py")
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.setattr(code, "workspace", lambda: tmp_path)
    monkeypatch.setattr(BUS, "emit", lambda *a, **k: None)
    return tmp_path


def test_choose_prefers_requested_then_installed(monkeypatch):
    monkeypatch.setattr(agente, "installed", lambda: {"claude": False, "codex": False, "ollama": True})
    assert agente.choose() == "ollama" and agente.choose("modelo local") == "ollama"
    with pytest.raises(RuntimeError, match="Claude Code não está instalado"):
        agente.choose("Claude")
    with pytest.raises(ValueError):
        agente.choose("cursor")


def test_start_and_redirect_require_confirmation():
    assert is_dangerous("agente_programar", {}) and is_dangerous("agente_mensagem", {})
    assert not is_dangerous("agente_progresso", {}) and not is_dangerous("agente_parar", {})


def test_programar_opens_console_window_with_framed_request(workspace, monkeypatch):
    monkeypatch.setattr(agente, "installed", lambda: {"claude": True, "codex": False, "ollama": False})
    launched = []

    class FakePopen:
        pid = 4242

        def __init__(self, cmd, cwd=None, creationflags=0):
            launched.append((cmd, cwd, creationflags))

        def poll(self):
            return None
    monkeypatch.setattr(agente.subprocess, "Popen", FakePopen)
    monkeypatch.setattr(agente.threading, "Thread", lambda **k: type("T", (), {"start": lambda self: None})())
    result = agente.agente_programar("Loja Virtual", "um site de loja com carrinho", ctx=Context({}))
    folder = workspace / "loja-virtual"
    cmd, cwd, flags = launched[0]
    assert cmd[-2:] == ["claude", ""] and str(agente.RUNNER) in cmd and Path(cwd) == folder
    assert flags == getattr(agente.subprocess, "CREATE_NEW_CONSOLE", 0) and "janela do CMD" in result
    request = (folder / ".viv" / "agente_pedido.txt").read_text(encoding="utf-8")
    assert "EXECUTAR:" in request and request.endswith("Pedido do usuário: um site de loja com carrinho")
    assert agente.state(folder)["pid"] == 4242


def test_watch_tells_viv_when_agent_finishes(workspace):
    folder = workspace / "jogo"
    told = []
    agente._save_state(folder, {"agente": "claude", "estado": "terminou", "resumo": "Fiz o jogo.", "pid": 7})
    process = type("P", (), {"pid": 7, "poll": lambda self: None})()
    agente._watch(type("C", (), {"notify": told.append})(), folder, process, poll=0)
    assert "[Agente de código]" in told[0] and "Fiz o jogo." in told[0] and "terminou" in told[0]


def test_watch_reports_window_closed_midway(workspace):
    folder = workspace / "jogo"
    told = []
    agente._save_state(folder, {"agente": "codex", "estado": "trabalhando", "pid": 8})
    process = type("P", (), {"pid": 8, "poll": lambda self: 1})()
    agente._watch(type("C", (), {"notify": told.append})(), folder, process, poll=0)
    assert agente.state(folder)["estado"] == "parado" and "parou sem terminar" in told[0]


def test_watch_stays_quiet_when_viv_stopped_it(workspace):
    folder = workspace / "jogo"
    told = []
    agente._save_state(folder, {"agente": "claude", "estado": "parado", "parado_pela_viv": True, "pid": 9})
    agente._watch(type("C", (), {"notify": told.append})(), folder, type("P", (), {"pid": 9, "poll": lambda s: None})(), poll=0)
    assert told == []


def test_progress_reads_log_tail(workspace, monkeypatch):
    folder = workspace / "jogo"
    agente._save_state(folder, {"agente": "claude", "estado": "terminou", "resumo": "Pronto.", "inicio": 0})
    (folder / ".viv" / "agente.log").write_text("> Write: index.html\n> Bash: npm test\n", encoding="utf-8")
    text = agente.agente_progresso("jogo", ctx=Context({}))
    assert "terminou" in text and "npm test" in text and "Pronto." in text


def test_runner_parses_claude_stream_and_keeps_session(tmp_path, monkeypatch):
    events = [json.dumps({"type": "system", "subtype": "init", "session_id": "s1"}),
              json.dumps({"type": "assistant", "message": {"content": [
                  {"type": "text", "text": "Vou criar o jogo."},
                  {"type": "tool_use", "name": "Write", "input": {"file_path": "index.html"}}]}}),
              json.dumps({"type": "result", "result": "Jogo pronto.\nEXECUTAR: python jogo.py", "is_error": False}), 0]
    monkeypatch.setattr(runner.shutil, "which", lambda name: "claude.cmd")
    seen = {}

    def fake_lines(cmd, folder, request):
        seen["cmd"] = cmd
        yield from events
    monkeypatch.setattr(runner, "_lines", fake_lines)
    said, kept = [], []
    summary, session = runner.run_claude(tmp_path, "pedido", "antiga", "", said.append, lambda s: kept.append(s) or s)
    assert "--resume" in seen["cmd"] and "antiga" in seen["cmd"] and kept == ["s1"] and session == "s1"
    assert summary.startswith("Jogo pronto.") and any("Write" in line for line in said)


def test_runner_main_saves_state_command_and_history(tmp_path, monkeypatch):
    folder = tmp_path / "jogo"
    (folder / ".viv").mkdir(parents=True)
    (folder / ".viv" / "agente_pedido.txt").write_text("Pedido do usuário: um jogo", encoding="utf-8")
    monkeypatch.setitem(runner.RUNNERS, "claude", lambda f, r, s, m, say, keep: ("Pronto, é só rodar.\nEXECUTAR: `python jogo.py`", keep("s2")))
    monkeypatch.setattr("builtins.input", lambda *a: "")
    monkeypatch.setattr(runner.os, "name", "posix")
    commits = []
    monkeypatch.setattr(code, "_commit", lambda f, m: commits.append(m))
    runner.main(folder, "claude")
    state = json.loads((folder / ".viv" / "agente.json").read_text(encoding="utf-8"))
    assert state["estado"] == "terminou" and state["sessao"] == "s2" and state["resumo"] == "Pronto, é só rodar."
    assert code._meta(folder)["executar"] == "python jogo.py" and commits
    assert "um jogo" in (folder / ".viv" / "agente.log").read_text(encoding="utf-8")


def test_runner_main_records_failure(tmp_path, monkeypatch):
    folder = tmp_path / "jogo"
    (folder / ".viv").mkdir(parents=True)
    (folder / ".viv" / "agente_pedido.txt").write_text("x", encoding="utf-8")

    def boom(*a):
        raise RuntimeError("o Codex não está instalado")
    monkeypatch.setitem(runner.RUNNERS, "codex", boom)
    monkeypatch.setattr("builtins.input", lambda *a: "")
    monkeypatch.setattr(runner.os, "name", "posix")
    monkeypatch.setattr(code, "_commit", lambda f, m: None)
    runner.main(folder, "codex")
    state = json.loads((folder / ".viv" / "agente.json").read_text(encoding="utf-8"))
    assert state["estado"] == "falhou" and "não está instalado" in state["resumo"]


def test_programar_hands_the_saved_briefing_to_the_agent(workspace, monkeypatch):
    from viv.tools import planejar
    launched = []
    monkeypatch.setattr(agente.subprocess, "Popen", lambda cmd, cwd=None, creationflags=0: launched.append(cmd) or type("P", (), {"pid": 7, "poll": lambda self: None})())
    monkeypatch.setattr(agente.threading, "Thread", lambda **k: type("T", (), {"start": lambda self: None})())
    folder = workspace / "jogo"
    planejar.write(folder, "um jogo", {"briefing": "# Jogo\n## Visão\nUm detetive gato." + " x" * 120, "resumo": "jogo"})
    agente.agente_programar("jogo", "um jogo que me surpreenda", ctx=Context({}))
    request = (folder / ".viv" / "agente_pedido.txt").read_text(encoding="utf-8")
    assert "Briefing detalhado" in request and "Um detetive gato." in request and "Antes de codar" in request
