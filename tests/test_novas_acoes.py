"""Miniatura, ações agendadas, clicar na tela, chat com modelos locais e humores negativos."""
import json
from datetime import datetime

import pytest

from tests.test_server import ORIGIN
from viv import mini
from viv.mood import FRUSTRATED_FOR, HURT_FOR, Mood
from viv.schedule import LATE, Schedule
from viv.tools import agenda, desktop, local, registry


class Clock:
    def __init__(self, now=1_000_000.0):
        self.now = now

    def __call__(self):
        return self.now


# ---- humores negativos -----------------------------------------------------------------------------
def test_one_rude_remark_is_enough_to_sour_her_and_an_apology_mends_it(tmp_path):
    mood = Mood(str(tmp_path / "h.json"), clock=Clock())
    mood.hear("anda logo, que demora")
    assert mood.name == "impaciente"
    mood.hear("desculpa")
    assert mood.name == "serena"


def test_an_insult_hurts_for_a_while_and_then_passes(tmp_path):
    clock = Clock()
    mood = Mood(str(tmp_path / "h.json"), clock=clock)
    mood.hear("sua burra")
    assert mood.name == "magoada" and "magoada" in mood.prompt()
    clock.now += HURT_FOR + 3 * 3600
    assert mood.name == "serena"
    mood.hear("sua idiota")
    mood.hear("foi mal, me perdoa")
    assert mood.name != "magoada", "o pedido de desculpa desfaz a mágoa na hora"


def test_repeated_errors_frustrate_her_and_criticism_counts(tmp_path):
    clock = Clock()
    mood = Mood(str(tmp_path / "h.json"), clock=clock)
    mood.feel("erro"); mood.feel("erro")
    assert mood.name == "serena"
    mood.feel("erro")
    assert mood.name == "frustrada"
    clock.now += FRUSTRATED_FOR + 3 * 3600
    assert mood.name == "serena"
    mood.hear("tá errado, não foi isso que eu pedi"); mood.hear("errou de novo")
    assert mood.name == "impaciente"


def test_being_woken_and_ignored_bores_her(tmp_path):
    mood = Mood(str(tmp_path / "h.json"), clock=Clock())
    mood.feel("ignorada")
    assert mood.name == "serena"
    mood.feel("ignorada")
    assert mood.name == "entediada" and mood.state()["label"] == "Entediada" and len(mood.state()["palette"]) == 3


# ---- miniatura ---------------------------------------------------------------------------------------
def test_miniature_position_follows_the_chosen_corner_inside_the_work_area():
    area, size = (48, 0, 1600, 900), (184, 136)
    assert mini.position("inferior direito", area, size, 18) == (1600 - 184 - 18, 900 - 136 - 18)
    assert mini.position("Superior Esquerdo", area, size, 18) == (48 + 18, 18)
    assert mini.position("embaixo à esquerda", area, size, 18) == (66, 900 - 136 - 18)
    assert mini.position("qualquer coisa", area, size, 18) == mini.position("inferior direito", area, size, 18)


class _Proc:
    def __init__(self):
        self.alive = True

    def poll(self):
        return None if self.alive else 0

    def terminate(self):
        self.alive = False


class _Settings(dict):
    def get(self, key):
        return self[key]


def test_miniature_opens_while_the_window_is_minimized_and_closes_when_it_returns():
    settings = _Settings({"miniatura.ativa": True, "miniatura.canto": "inferior direito",
                          "avatar.tamanho": 100, "avatar.opacidade": 100})
    state, spawned = ["aberta"], []

    def spawn(url, corner, look):
        spawned.append((url, corner, _Proc(), look))
        return spawned[-1][2]
    watcher = mini.Mini(settings, "http://x/mini", state=lambda: state[0], spawn=spawn, restore=lambda: True)
    watcher.tick()
    assert spawned == []
    state[0] = "minimizada"
    watcher.tick(); watcher.tick()
    assert len(spawned) == 1 and spawned[0][:2] == ("http://x/mini", "inferior direito")
    settings["miniatura.canto"] = "superior esquerdo"          # mudar o canto reabre no lugar novo
    watcher.tick()
    assert len(spawned) == 2 and not spawned[0][2].alive and spawned[1][1] == "superior esquerdo"
    state[0] = "aberta"
    watcher.tick()
    assert not spawned[1][2].alive
    state[0], settings["miniatura.ativa"] = "minimizada", False
    watcher.tick()
    assert len(spawned) == 2, "desligada nas configurações, não abre"
    settings["miniatura.ativa"] = True
    watcher.tick()
    assert len(spawned) == 3 and spawned[2][3] == (100, 100)
    settings["avatar.opacidade"], settings["avatar.tamanho"] = 40, 999      # tamanho fora do limite fica no máximo
    watcher.tick()
    watcher.stop()
    assert len(spawned) == 4 and not spawned[2][2].alive and not spawned[3][2].alive and spawned[3][3] == (300, 40)


def test_miniature_size_scales_the_window():
    assert mini.scaled((200, 156), 150) == (300, 234) and mini.scaled((200, 156), 50) == (100, 78)
    assert mini.look_of(_Settings({"avatar.tamanho": "abc", "avatar.opacidade": 5})) == (100, 20)


def test_miniature_page_is_served_and_a_click_restores_the_window():
    from fastapi.testclient import TestClient
    from server import create_app
    from tests.test_server import CFG, FakeAudio, FakeGate, FakeSpeaker, FakeViv
    app = create_app(FakeViv(), FakeGate(), FakeAudio(), CFG, FakeSpeaker())
    with TestClient(app) as client:
        page = client.get("/mini")
        assert page.status_code == 200 and "/static/avatar.js?v=" in page.text and "/static/mini.js?v=" in page.text
        assert client.post("/api/mini/abrir").status_code == 403
        assert client.post("/api/mini/abrir", headers=ORIGIN).json() == {"ok": False}
        restored = []
        app.state.mini = type("M", (), {"restore": lambda self: restored.append(1) or True})()
        assert client.post("/api/mini/abrir", headers=ORIGIN).json() == {"ok": True} and restored == [1]
        assert client.get("/", params={"name": "../config.yaml"}).text.lstrip().startswith("<!doctype html>")


# ---- clicar no que está na tela ----------------------------------------------------------------------
def test_locate_turns_the_models_box_into_pixel_coordinates():
    from PIL import Image
    asked = []

    def ask(prompt):
        asked.append(prompt)
        return '```json\n{"box_2d": [100, 200, 300, 400], "nome": "Salvar"}\n```'
    assert desktop.locate(None, "botão Salvar", ask=ask, grab=lambda: Image.new("RGB", (2000, 1000))) == (600, 200, "Salvar")
    assert "botão Salvar" in asked[0]
    with pytest.raises(RuntimeError, match="não achei"):
        desktop.locate(None, "botão Sumido", ask=lambda p: '{"box_2d": null}', grab=lambda: Image.new("RGB", (10, 10)))


def test_click_on_screen_scales_to_mouse_coordinates_and_clicks(monkeypatch):
    from PIL import Image, ImageGrab
    clicks = []

    class Gui:
        def size(self):
            return (1000, 500)                                  # tela com escala: a captura tem o dobro de pixels

        def moveTo(self, x, y, duration=0):
            clicks.append(("move", x, y))

        def click(self, **how):
            clicks.append(("click", how["button"], how["clicks"]))
    monkeypatch.setattr(desktop, "_gui", lambda: Gui())
    monkeypatch.setattr(desktop, "locate", lambda ctx, target: (600, 200, "Salvar"))
    monkeypatch.setattr(ImageGrab, "grab", lambda: Image.new("RGB", (2000, 1000)))
    assert desktop.tela_clicar("botão Salvar", duplo=True) == "cliquei em “Salvar” (300,100)"
    assert clicks == [("move", 300, 100), ("click", "left", 2)]
    with pytest.raises(ValueError):
        desktop.tela_clicar("x", botao="quinto")


def test_keys_can_be_pressed_several_times(monkeypatch):
    pressed = []
    monkeypatch.setattr(desktop, "_gui", lambda: type("G", (), {"hotkey": lambda self, *keys: pressed.append(keys)})())
    assert desktop.hotkey("Ctrl + S") == "pressionado Ctrl + S"
    assert desktop.hotkey("down", vezes=3).endswith("3 vezes")
    assert pressed == [("ctrl", "s"), ("down",), ("down",), ("down",)]


# ---- ações agendadas ----------------------------------------------------------------------------------
def test_when_understands_the_usual_ways_of_saying_a_time():
    now = datetime(2026, 11, 17, 22, 0)
    assert agenda.parse_when("21:30", now) == datetime(2026, 11, 18, 21, 30)           # já passou hoje: amanhã
    assert agenda.parse_when("hoje às 23h", now) == datetime(2026, 11, 17, 23, 0)
    assert agenda.parse_when("amanhã 8h", now) == datetime(2026, 11, 18, 8, 0)
    assert agenda.parse_when("18/11 09:00", now) == datetime(2026, 11, 18, 9, 0)
    assert agenda.parse_when("2026-11-20 09:05", now) == datetime(2026, 11, 20, 9, 5)
    assert agenda.parse_when("em 20 minutos", now) == datetime(2026, 11, 17, 22, 20)
    assert agenda.parse_when("daqui a 2 horas", now) == datetime(2026, 11, 18, 0, 0)
    for bad in ("mais tarde", "25:00", "31/02 10:00"):
        with pytest.raises(ValueError):
            agenda.parse_when(bad, now)


def test_schedule_runs_at_the_time_once_survives_restart_and_skips_what_is_too_late(tmp_path):
    clock, ran, reports = Clock(), [], []
    path = str(tmp_path / "agenda.json")

    def run(tool, args):
        ran.append((tool, args))
        return "erro: sem rede" if tool == "falha" else "feito"
    make = lambda: Schedule(path, run, lambda job, result, outcome: reports.append((job["text"], outcome)), clock=clock)
    schedule = make()
    schedule.add(clock.now + 60, "abrir", {"nome": "Spotify"}, "Abrir o Spotify")
    schedule.add(clock.now + 120, "falha", {}, "Vai falhar")
    schedule.add(clock.now + 30, "diaria", {}, "Bom dia", daily=True)
    assert schedule.run_due() == 0 and ran == []
    schedule = make()                                           # reiniciar não perde nada
    assert [j["text"] for j in schedule.pending()] == ["Bom dia", "Abrir o Spotify", "Vai falhar"]
    clock.now += 61
    assert schedule.run_due() == 2 and schedule.run_due() == 0
    assert ran == [("abrir", {"nome": "Spotify"}), ("diaria", {})] or ran == [("diaria", {}), ("abrir", {"nome": "Spotify"})]
    assert ("Abrir o Spotify", "feita") in reports
    assert [j["text"] for j in schedule.pending()] == ["Vai falhar", "Bom dia"], "a diária volta para amanhã"
    clock.now += 60
    schedule.run_due()
    assert reports[-1] == ("Vai falhar", "falhou")
    assert schedule.cancel(5) is None and schedule.cancel(1)["text"] == "Bom dia" and schedule.pending() == []
    schedule.add(clock.now + 10, "abrir", {}, "Atrasada")
    clock.now += LATE + 60                                      # a Viv estava fechada na hora
    ran.clear()
    schedule.run_due()
    assert ran == [] and reports[-1] == ("Atrasada", "perdida")


def test_scheduling_needs_confirmation_text_and_refuses_what_must_not_be_scheduled(tmp_path, monkeypatch):
    registry.load_all()
    now = datetime(2026, 11, 17, 22, 0)
    when, name, args, text = agenda.plan({"ferramenta": "system_volume", "argumentos": '{"percent": 30}', "quando": "23:00",
                                          "descricao": "Baixar o volume"}, now)
    assert (when, name, args, text) == (datetime(2026, 11, 17, 23, 0), "system_volume", {"percent": 30}, "Baixar o volume")
    _, name, args, text = agenda.plan({"ferramenta": "whatsapp_enviar", "quando": "amanhã 8h",
                                       "argumentos": json.dumps({"contato": "Ana", "mensagem": " bom dia "})}, now)
    assert args == {"contato": "Ana", "mensagem": "bom dia"} and text == "Enviar WhatsApp para Ana: “bom dia”"
    for bad in ({"ferramenta": "nao_existe", "quando": "23:00"}, {"ferramenta": "desktop_run_command", "quando": "23:00"},
                {"ferramenta": "acao_agendar", "quando": "23:00"}, {"ferramenta": "system_volume", "quando": "ontem"},
                {"ferramenta": "system_volume", "quando": "23:00", "argumentos": "[1]"},
                {"ferramenta": "whatsapp_enviar", "quando": "23:00", "argumentos": '{"contato": "Ana"}'}):
        with pytest.raises(ValueError):
            agenda.plan(bad, now)
    assert registry.is_dangerous("acao_agendar", {}), "agendar sempre passa pela confirmação do usuário"
    ctx = registry.Context({})
    ctx.schedule = Schedule(str(tmp_path / "a.json"), lambda *a: "ok", lambda *a: None)
    result = agenda.acao_agendar("system_volume", '{"percent": 30}', "em 10 minutos", "Baixar o volume", ctx=ctx)
    assert result.startswith("agendado para") and "1. " in agenda.acoes_agendadas(ctx=ctx)
    assert agenda.acao_cancelar(1, ctx=ctx) == "cancelada: Baixar o volume"
    assert agenda.acoes_agendadas(ctx=ctx) == "nenhuma ação agendada"


# ---- chat com um modelo local -------------------------------------------------------------------------
def test_local_chat_streams_the_answer_and_retries_without_thinking_flag():
    seen, bodies = [], []

    def stream(body):
        bodies.append(dict(body))
        if "think" in body:
            raise RuntimeError('Ollama respondeu 400: "this model does not support thinking"')
        yield json.dumps({"message": {"content": "Era uma "}})
        yield ""
        yield json.dumps({"message": {"content": "vez."}, "done": True})
    text = local.chat(None, "rpg:8b", [{"role": "user", "content": "conta uma história"}], seen.append, stream=stream)
    assert text == "Era uma vez." and seen == ["Era uma ", "Era uma vez."]
    assert len(bodies) == 2 and bodies[1]["model"] == "rpg:8b" and bodies[1]["messages"][0]["role"] == "system"
    assert bodies[1]["messages"][-1] == {"role": "user", "content": "conta uma história"}
    with pytest.raises(RuntimeError, match="não devolveu"):
        local.chat(None, "m", [], stream=lambda body: iter([json.dumps({"done": True})]))


def test_chat_lists_models_and_talks_to_the_chosen_one_without_waking_viv(monkeypatch):
    import time
    from fastapi.testclient import TestClient
    from server import create_app
    from tests.test_server import CFG, FakeAudio, FakeGate, FakeSpeaker, FakeViv
    from viv.bus import BUS
    monkeypatch.setattr(local, "installed", lambda ctx, http=None: [{"nome": "rpg:8b", "gb": 4.9}, {"nome": "nomic-embed-text:latest", "gb": 0.3}])
    histories = []

    def fake_chat(ctx, model, messages, on_text=None, stream=None):
        histories.append([m["content"] for m in messages])
        on_text("Você entra")
        return "Você entra na taverna."
    monkeypatch.setattr(local, "chat", fake_chat)
    events = []
    monkeypatch.setattr(BUS, "emit", lambda channel, text="", **extra: events.append((channel, text, extra)))
    viv = FakeViv()
    with TestClient(create_app(viv, FakeGate(), FakeAudio(), CFG, FakeSpeaker())) as client:
        assert client.get("/api/chat/modelos").json()["modelos"] == [{"id": "viv", "nome": "Viv"}, {"id": "rpg:8b", "nome": "rpg:8b (4.9 GB)"}]
        assert client.post("/api/chat", json={"texto": "oi", "modelo": "outro"}, headers=ORIGIN).status_code == 400
        assert client.post("/api/chat", json={"texto": "Começa a aventura\nagora", "modelo": "rpg:8b"}, headers=ORIGIN).status_code == 200
        for _ in range(200):
            if any(e[0] == "chat" and e[2].get("final") for e in events):
                break
            time.sleep(0.01)
        assert viv.calls == []
        final = [e for e in events if e[0] == "chat" and e[2].get("final")][0]
        assert final[1] == "Você entra na taverna." and final[2]["model"] == "rpg:8b" and final[2]["reply"] is True
        events.clear()
        client.post("/api/chat", json={"texto": "sigo em frente", "modelo": "rpg:8b"}, headers=ORIGIN)
        for _ in range(200):
            if any(e[0] == "chat" and e[2].get("final") for e in events):
                break
            time.sleep(0.01)
        assert histories[1] == ["Começa a aventura\nagora", "Você entra na taverna.", "sigo em frente"], "o modelo relê a conversa"
        assert client.post("/api/chat/nova", json={"modelo": "rpg:8b"}, headers=ORIGIN).status_code == 200
        events.clear()
        client.post("/api/chat", json={"texto": "de novo", "modelo": "rpg:8b"}, headers=ORIGIN)
        for _ in range(200):
            if any(e[0] == "chat" and e[2].get("final") for e in events):
                break
            time.sleep(0.01)
        assert histories[2] == ["de novo"]


def test_notices_page_for_the_minimized_viv_uses_the_same_toasts():
    from fastapi.testclient import TestClient
    from server import create_app
    from tests.test_server import CFG, FakeAudio, FakeGate, FakeSpeaker, FakeViv
    app = create_app(FakeViv(), FakeGate(), FakeAudio(), CFG, FakeSpeaker())
    with TestClient(app) as client:
        page = client.get("/avisos")
        assert page.status_code == 200 and "/static/toast.js?v=" in page.text and "/static/avisos.js?v=" in page.text


def test_miniature_eyes_follow_the_cursor_anywhere_on_screen():
    rect = (1400, 780, 1600, 900)
    assert mini.gaze((1500, 840), rect) == (0.0, 0.0)
    left, up = mini.gaze((100, 100), rect)
    assert left < -0.9 and up < -0.5 and abs(mini.gaze((5000, 840), rect)[0]) <= 1.2, "longe, olha no limite"
