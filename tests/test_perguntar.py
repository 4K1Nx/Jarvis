import pytest
from fastapi.testclient import TestClient

from server import create_app
from tests.test_server import CFG, ORIGIN, FakeAudio, FakeGate
from viv.bus import BUS
from viv.tools import hud


class Viv:
    def __init__(self):
        self.state = type("S", (), {"value": "listening"})()
        self.told = []

    def notify(self, text):
        self.told.append(text)


@pytest.fixture
def events(monkeypatch):
    seen = []
    monkeypatch.setattr(BUS, "emit", lambda channel, text="", **extra: seen.append((channel, text, extra)))
    hud.OPEN.clear()
    yield seen
    hud.OPEN.clear()


def test_question_needs_two_to_five_options(events):
    with pytest.raises(ValueError):
        hud.perguntar("Tamanho?", ["Curta"])
    with pytest.raises(ValueError):
        hud.perguntar("Tamanho?", list("abcdef"))


def test_question_goes_to_the_screen_with_the_suggestion(events):
    assert "voz alta" in hud.perguntar("Tamanho?", ["Curta", "Média"], "Média")
    assert events == [("ask", "Tamanho?", {"options": ["Curta", "Média"], "suggestion": "Média"})]
    hud.perguntar("Tema?", ["Claro", "Escuro"], "Roxo")              # sugestão que não é opção não vale
    assert events[-1][2]["suggestion"] == ""


def test_answer_counts_once_and_only_for_an_open_option(events):
    hud.perguntar("Tamanho?", ["Curta", "Média"])
    assert not hud.answer("Tamanho?", "Enorme") and not hud.answer("Outra?", "Curta")
    assert hud.answer("Tamanho?", "Curta") and not hud.answer("Tamanho?", "Curta")


def test_closing_removes_every_question(events):
    hud.perguntar("Tamanho?", ["Curta", "Média"])
    hud.close_questions()
    assert hud.OPEN == {} and events[-1][0] == "ask_done" and not hud.answer("Tamanho?", "Curta")


def test_click_reaches_the_model_only_for_a_real_option(events):
    viv = Viv()
    client = TestClient(create_app(viv, FakeGate(), FakeAudio(), CFG))
    hud.perguntar("Tamanho?", ["Curta", "Média"])
    bad = client.post("/api/answer", json={"pergunta": "Tamanho?", "opcao": "Enorme"}, headers=ORIGIN)
    assert bad.status_code == 400 and viv.told == []
    assert client.post("/api/answer", json={"pergunta": "Tamanho?", "opcao": "Curta"}).status_code == 403
    good = client.post("/api/answer", json={"pergunta": "Tamanho?", "opcao": "Curta"}, headers=ORIGIN)
    assert good.status_code == 200 and len(viv.told) == 1 and "Curta" in viv.told[0]
