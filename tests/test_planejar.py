"""Briefing de programação: perguntas só quando faltam, pesquisa e prompt detalhado salvo no projeto."""
import pytest

from viv.tools import planejar
from viv.tools.registry import Context

BRIEF = "# Caso do Farol\n## Visão\n" + "detalhe concreto " * 30 + "fim"


def fake_ask(analysis):
    asked = []

    def ask(ctx, prompt, as_json=False):
        asked.append(prompt)
        return analysis if as_json else BRIEF
    return ask, asked


SEARCH = lambda query, n: [{"title": "Return of the Obra Dinn", "url": "https://x.test/a", "body": "dedução por lógica"}]
FETCH = lambda url: "<p>Jogo de dedução com caderno de pistas.</p>"


def test_missing_essentials_become_questions_before_any_research():
    ask, asked = fake_ask({"perguntas": ["É para celular ou PC?"], "criativo": False, "buscas": ["x"]})
    searched = []
    result = planejar.plan(None, "um app de finanças", ask=ask, search=lambda q, n: searched.append(q) or [])
    assert result["perguntas"] == ["É para celular ou PC?"] and searched == [] and len(asked) == 1


def test_creative_requests_never_ask_and_get_an_original_concept():
    ask, asked = fake_ask({"perguntas": ["Qual gênero?"], "criativo": True, "premissas": ["web"], "buscas": ["jogos de investigação"]})
    result = planejar.plan(None, "um jogo que me surpreenda", ask=ask, search=SEARCH, fetch=FETCH)
    assert result["briefing"] == BRIEF and "ORIGINAL" in asked[1] and "caderno de pistas" in asked[1]
    assert "Critérios de aceite" in asked[1] and "Como testar" in asked[1]


def test_answers_skip_the_questions_and_the_briefing_is_saved(tmp_path, monkeypatch):
    monkeypatch.setattr(planejar, "project_dir", lambda name: tmp_path / name)
    monkeypatch.setattr(planejar._llm, "ask", fake_ask({"perguntas": ["PC?"], "criativo": False, "buscas": []})[0])
    monkeypatch.setattr("viv.tools.web.search", SEARCH)
    monkeypatch.setattr("viv.tools.sources.page_text", lambda url, fetch=None: "")
    out = planejar.agente_planejar("financas", "um app de finanças", respostas="PC, só eu uso", ctx=Context({}))
    assert "briefing pronto" in out and planejar.saved(tmp_path / "financas") == BRIEF


def test_short_briefing_is_an_error():
    ask, _ = fake_ask({"perguntas": [], "buscas": []})
    with pytest.raises(RuntimeError):
        planejar.plan(None, "x", ask=lambda c, p, as_json=False: {} if as_json else "curto", search=SEARCH, fetch=FETCH)
