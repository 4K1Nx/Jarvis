"""Modelos locais do Ollama: quando entram no lugar do Gemini e como são baixados."""
import json

import pytest

from viv.bus import BUS
from viv.tools import _llm, local, modelos, registry, vision
from viv.tools.registry import Context

TAGS = {"models": [{"name": "qwen3:8b", "size": 5_200_000_000}, {"name": "gemma3:4b", "size": 3_300_000_000}]}


class Ollama:
    """Servidor falso: responde /api/tags e /api/generate e guarda os pedidos."""
    def __init__(self, tags=TAGS, answer="resposta local", reject_think=False):
        self.tags, self.answer, self.reject_think, self.calls = tags, answer, reject_think, []

    def __call__(self, method, url, payload=None, timeout=0):
        if url.endswith("/api/tags"):
            return self.tags
        self.calls.append(dict(payload))
        if self.reject_think and "think" in payload:
            raise RuntimeError('Ollama respondeu 400: "gemma3:4b" does not support thinking')
        return {"response": self.answer}


class Gemini:
    def __init__(self, text=None, error=None):
        self.text, self.error, self.models, self.calls = text, error, self, 0

    def generate_content(self, model, contents, config=None):
        self.calls += 1
        if self.error:
            raise RuntimeError(self.error)
        return type("R", (), {"text": self.text})()


@pytest.fixture
def ollama(monkeypatch):
    monkeypatch.setattr(BUS, "emit", lambda *a, **k: None)
    monkeypatch.setattr(_llm.time, "sleep", lambda s: None)
    server = Ollama()
    monkeypatch.setattr(local, "_http", server)
    return server


def ctx(mode="reserva", client=None):
    return Context({"tools": {"local": {"mode": mode}}}, client=client)


def test_reserve_mode_uses_gemini_and_falls_back_when_the_quota_ends(ollama):
    assert _llm.ask(ctx(client=Gemini("do gemini")), "oi") == "do gemini" and ollama.calls == []
    assert _llm.ask(ctx(client=Gemini(error="429 RESOURCE_EXHAUSTED")), "oi") == "resposta local"
    assert ollama.calls[0]["model"] == "qwen3:8b" and ollama.calls[0]["options"]["num_ctx"] == local.CONTEXT
    assert _llm.ask(ctx(client=None), "oi") == "resposta local"                 # sem conexão com o Gemini também


def test_economy_mode_answers_locally_first_and_gemini_covers_failures(ollama, monkeypatch):
    gemini = Gemini("do gemini")
    assert _llm.ask(ctx("economia", gemini), "oi") == "resposta local" and gemini.calls == 0
    ollama.answer = ""                                                          # o modelo local não respondeu
    assert _llm.ask(ctx("economia", gemini), "oi") == "do gemini"


def test_off_mode_and_long_prompts_never_go_local(ollama):
    with pytest.raises(RuntimeError, match="sobrecarregado"):
        _llm.ask(ctx("desligado", Gemini(error="503 unavailable")), "oi")
    with pytest.raises(RuntimeError, match="sobrecarregado"):
        _llm.ask(ctx("reserva", Gemini(error="503 unavailable")), "x" * (local.MAX_CHARS + 1))
    gemini = Gemini("do gemini")
    assert _llm.ask(ctx("economia", gemini), "x" * (local.MAX_CHARS + 1)) == "do gemini"
    assert ollama.calls == []


def test_json_answers_are_parsed_and_models_without_thinking_still_work(ollama):
    ollama.answer, ollama.reject_think = json.dumps({"buscas": ["a"]}), True
    assert _llm.ask(ctx("economia"), "plano", as_json=True) == {"buscas": ["a"]}
    assert ollama.calls[0]["format"] == "json" and "think" in ollama.calls[0] and "think" not in ollama.calls[1]


def test_missing_model_tells_viv_to_ask_before_downloading(ollama):
    ollama.tags = {"models": []}
    with pytest.raises(RuntimeError) as error:
        _llm.ask(ctx(client=Gemini(error="429 RESOURCE_EXHAUSTED")), "oi")
    assert "qwen3:8b não está instalado" in str(error.value) and "modelo_baixar" in str(error.value) and "sobrecarregado" in str(error.value)


def test_screen_analysis_falls_back_to_the_local_vision_model(ollama, tmp_path, monkeypatch):
    shot = tmp_path / "tela.png"
    shot.write_bytes(b"png")
    monkeypatch.setattr(vision, "capture", lambda path: str(shot))
    assert vision.look(ctx(client=Gemini(error="Read timed out")), "o que há?") == "resposta local"
    assert ollama.calls[0]["model"] == "gemma3:4b" and ollama.calls[0]["images"]
    with pytest.raises(RuntimeError, match="sobrecarregado"):
        vision.look(ctx("desligado", Gemini(error="Read timed out")), "o que há?")


def test_listing_shows_what_is_installed_and_what_is_missing(ollama):
    text = modelos.modelos_locais(ctx=ctx())
    assert "qwen3:8b (5.2 GB)" in text and "qwen2.5-coder:7b — programar" in text and "modo de uso: reserva" in text
    ollama.tags = {"models": []}
    assert "pergunte se pode" in modelos.modelos_locais(ctx=ctx())


def test_download_needs_confirmation_a_valid_name_and_reports_progress(ollama, monkeypatch):
    registry.load_all()
    assert registry.is_dangerous("modelo_baixar", {})
    assert "llama3.2:3b" in registry.confirm_text("modelo_baixar", {"nome": "llama3.2:3b"})
    with pytest.raises(ValueError, match="inválido"):
        registry.confirm_text("modelo_baixar", {"nome": "qwen3:8b; rm -rf /"})
    steps = []
    lines = [json.dumps({"status": "pulling", "total": 100, "completed": 40}), "", json.dumps({"status": "success"})]
    local.pull(ctx(), "llama3.2:3b", lambda label, value: steps.append((label, value)), stream=lambda: lines)
    assert steps[0] == ("Baixando llama3.2:3b: pulling", 0.4) and steps[-1][1] is None
    with pytest.raises(RuntimeError, match="falhou"):
        local.pull(ctx(), "x", stream=lambda: [json.dumps({"error": "pull model manifest: file does not exist"})])
    assert modelos.modelo_baixar("qwen3:8b", ctx=ctx()) == "o modelo qwen3:8b já está instalado"
