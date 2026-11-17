"""Gráficos, monitor do PC, teste de internet, inicialização do Windows e plano de energia."""
import pytest

from viv.bus import BUS
from viv.tools import charts, monitor, registry

DATA = {"cpu": 12.0, "memoria": 50.0, "disco": 70.0, "ram_gb": 16.0, "ram_total_gb": 32.0, "disco_livre_gb": 30.0,
        "down_mbps": 1.5, "up_mbps": 0.5, "bateria": None}


@pytest.fixture
def cards(monkeypatch):
    seen = []
    monkeypatch.setattr(BUS, "emit", lambda channel, text="", **extra: seen.append((channel, text, extra)))
    return seen


# ---- gráficos ---------------------------------------------------------------
def test_chart_keeps_only_real_numbers_and_short_texts():
    made = charts.chart("barras", [{"label": "a" * 99, "value": "3.456"}, {"label": "b", "value": "muito"},
                                   {"label": "c", "value": float("nan")}, {"value": 2}], "MB")
    assert made == {"type": "barras", "unit": "MB", "items": [{"label": "a" * 40, "value": 3.46}, {"label": "", "value": 2.0}]}
    with pytest.raises(ValueError, match="medidores, barras, linhas ou pizza"):
        charts.chart("radar", [{"label": "a", "value": 1}])
    with pytest.raises(ValueError, match="pelo menos dois"):
        charts.chart("linhas", [{"label": "a", "value": 1}])
    assert charts.chart("pizza", [{"label": "a", "value": 0}, {"label": "b", "value": 0}])["type"] == "barras"
    assert len(charts.chart("medidores", [{"label": str(n), "value": n} for n in range(20)])["items"]) == 6


def test_chart_tool_shows_a_panel_and_checks_sizes(cards):
    assert "gráfico exibido" in charts.hud_grafico("Vendas", "barras", ["jan", "fev"], [10, 20], "R$")
    channel, title, extra = cards[-1]
    assert (channel, title, extra["kind"]) == ("card", "Vendas", "chart") and extra["chart"]["items"][1] == {"label": "fev", "value": 20.0}
    charts.hud_grafico("Uso", "medidores", ["CPU"], [40], "%", maximo=200)
    assert cards[-1][2]["chart"]["items"][0]["max"] == 200.0
    with pytest.raises(ValueError, match="mesmo tamanho"):
        charts.hud_grafico("x", "barras", ["a"], [1, 2])


# ---- monitor ---------------------------------------------------------------
class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def make(data=DATA):
    shown, told, clock, current = [], [], Clock(), dict(data)
    mon = monitor.Monitor(read=lambda: dict(current), notify=told.append, clock=clock,
                          show=lambda title, chart, body="", live="": shown.append((title, chart, body, live)), wait=lambda s: None)
    mon._ensure = lambda: None                       # os testes dão os passos na mão, sem thread
    return mon, shown, told, clock, current


def test_live_panel_updates_in_place_until_its_time_ends():
    mon, shown, told, clock, _ = make()
    mon.panel(10)
    assert mon.step() and shown[0][0] == "PC ao vivo" and shown[0][3] == "pc" and "1.5 Mbps" in shown[0][2]
    assert [i["label"] for i in shown[0][1]["items"]] == ["CPU", "Memória", "Disco usado"]
    clock.now = 11
    assert not mon.step() and len(shown) == 1 and told == []


def test_alert_fires_once_after_staying_above_the_limit_and_rearms_when_it_drops():
    mon, shown, told, clock, current = make()
    mon.watch("memoria", 90, 60)
    current["memoria"] = 95
    assert mon.step() and told == []                 # acabou de passar: espera sustentar
    clock.now = 21
    mon.step()
    assert len(told) == 1 and "Memória em 95%" in told[0] and "90%" in told[0]
    clock.now = 60
    mon.step()
    assert len(told) == 1                            # não repete enquanto continua alto
    current["memoria"] = 50
    mon.step()
    current["memoria"] = 96
    clock.now = 70
    mon.step()
    clock.now = 95
    mon.step()
    assert len(told) == 2                            # caiu e subiu de novo: avisa outra vez
    clock.now = 60 * 60 + 100
    assert not mon.step() and mon.alerts == []       # o prazo acabou


def test_alert_tool_validates_and_stop_cancels_everything(cards, monkeypatch):
    mon, *_ = make()
    monkeypatch.setattr(monitor, "_monitor", mon)
    ctx = registry.Context({})
    assert "Memória" in monitor.monitor_alerta("RAM", 90, ctx=ctx) and mon.alerts[0]["recurso"] == "memoria"
    with pytest.raises(ValueError, match="cpu, memoria ou disco"):
        monitor.monitor_alerta("gpu", 90, ctx=ctx)
    with pytest.raises(ValueError, match="1 a 100"):
        monitor.monitor_alerta("cpu", 150, ctx=ctx)
    assert "1 alerta" in monitor.monitor_parar(ctx=ctx) and mon.alerts == []


def test_status_text_and_gauges():
    assert monitor.describe(DATA).startswith("CPU 12%, memória 50% (16.0 de 32 GB), disco 70% usado (30 GB livres)")
    assert "bateria 80%" in monitor.describe({**DATA, "bateria": 80})
    assert len(monitor.gauges({**DATA, "bateria": 80})["items"]) == 4


# ---- internet ---------------------------------------------------------------
def test_speed_test_turns_bytes_into_megabits(cards):
    result = monitor.speed_test(ping=lambda http: 20.0, download=lambda http, s: (12_500_000, 2.0), upload=lambda http, s: (2_500_000, 2.0))
    assert result == {"ping_ms": 20.0, "down_mbps": 50.0, "up_mbps": 10.0}

    def broken(http, seconds=0):
        raise OSError("bloqueado")
    assert monitor.speed_test(ping=lambda http: 30.0, download=lambda http, s: (1_000_000, 1.0), upload=broken)["up_mbps"] == 0
    with pytest.raises(RuntimeError, match="fora do ar"):
        monitor.speed_test(ping=broken)
    assert monitor.judge(3).startswith("lenta") and monitor.judge(60).startswith("boa")


def test_speed_tool_shows_three_gauges(cards, monkeypatch):
    monkeypatch.setattr(monitor, "speed_test", lambda: {"ping_ms": 18.0, "down_mbps": 4.2, "up_mbps": 0})
    text = monitor.rede_velocidade()
    assert "download 4.2 Mbps" in text and "não foi possível medir" in text and "lenta" in text
    chart = [c for c in cards if c[2].get("kind") == "chart"][-1][2]["chart"]
    assert [i["label"] for i in chart["items"]] == ["Download", "Upload", "Latência"] and chart["items"][0]["max"] == 100.0


# ---- inicialização e energia ---------------------------------------------------------------
ENTRIES = [{"nome": "Steam", "comando": "steam.exe", "escopo": "usuario", "ativo": True},
           {"nome": "SteamVR", "comando": "vr.exe", "escopo": "usuario", "ativo": True},
           {"nome": "Driver", "comando": "d.exe", "escopo": "maquina", "ativo": True}]


def test_startup_entry_is_changed_only_when_the_name_is_unambiguous():
    written = []
    assert monitor.set_startup("steam", False, ENTRIES, lambda e, flag: written.append((e["nome"], flag)))["nome"] == "Steam"
    assert written == [("Steam", False)]
    with pytest.raises(ValueError, match="mais de um"):
        monitor.set_startup("ste", False, ENTRIES, lambda e, flag: None)
    with pytest.raises(ValueError, match="não achei"):
        monitor.set_startup("spotify", False, ENTRIES, lambda e, flag: None)

    def denied(entry, flag):
        raise PermissionError
    with pytest.raises(PermissionError, match="administrador"):
        monitor.set_startup("driver", False, ENTRIES, denied)


def test_startup_change_is_dangerous_and_power_plan_is_validated():
    registry.load_all()
    assert registry.is_dangerous("system_inicializacao_definir", {}) and not registry.is_dangerous("system_energia", {})
    calls = []

    def run(*args):
        calls.append(args)
        return "GUID do Esquema de Energia: 8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c  (Alto desempenho)"
    assert monitor.system_energia("desempenho", run=run) == "plano de energia agora: desempenho"
    assert calls[0] == ("/setactive", monitor.PLANS["desempenho"])
    assert monitor.system_energia(run=lambda *a: "GUID: 0000  (Meu plano)") == "plano de energia atual: Meu plano"
    with pytest.raises(ValueError, match="desempenho, equilibrado ou economia"):
        monitor.system_energia("turbo", run=run)


def test_daily_summary_is_structured_for_the_drawn_panel():
    from viv import briefing
    data = {"hora": "08:12", "dia": "segunda-feira, 16/11/2026", "rotina": ["09:00 reunião"], "lembretes": ["a", "b"],
            "emails_nao_lidos": 7, "whatsapp": [{"label": "Mãe", "unread": 2}], "disco_livre_pct": 8, "disco_livre_gb": 20, "erros": 0,
            "clima": {"city": "Fortaleza", "temp": 29, "desc": "Sol", "max": 32, "rain": 20, "min": 25, "feels": 31}}
    made = briefing.tiles(data)
    assert made["hora"] == "08:12" and made["clima"] == {"city": "Fortaleza", "temp": 29, "desc": "Sol", "max": 32, "rain": 20}
    assert [(n["label"], n["value"]) for n in made["numeros"]] == [("e-mails não lidos", 7), ("conversas esperando", 1),
                                                                   ("lembretes", 2), ("de disco livre", "8%")]
    assert made["numeros"][3]["tone"] == "bad"
    assert [g["titulo"] for g in made["listas"]] == ["Rotina de hoje", "Lembretes", "WhatsApp esperando resposta"]
    bare = briefing.tiles({"hora": "08:00", "dia": "x"})
    assert bare["clima"] is None and bare["listas"] == [] and bare["numeros"] == [{"label": "lembretes", "value": 0}]


def test_email_panel_sends_structured_rows(cards):
    from viv.tools import mail
    mail._panel("E-mails", [{"de": "Ana <ana@x.com>", "assunto": "Oi", "data": "16/11 07:40"}])
    extra = cards[-1][2]
    assert extra["emails"] == [{"n": 1, "de": "Ana <ana@x.com>", "assunto": "Oi", "data": "16/11 07:40"}] and "Ana" in extra["body"]
