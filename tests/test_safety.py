import numpy as np
import pytest

from viv.safety import Gate
from viv.tools import registry
from viv.tools.registry import Context, tool

CFG = {"safety": {"confirm_timeout_seconds": 30, "dangerous": []}}
AUDIO = np.zeros(16000, dtype=np.float32)


class FakeSpeaker:
    def __init__(self, owner=True, enrolled=True):
        self.owner, self.enrolled = owner, enrolled

    def is_owner(self, audio):
        return self.enrolled and self.owner


class FakeAudit:
    def __init__(self):
        self.events = []

    def record(self, event, **fields):
        self.events.append(event)


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


@pytest.fixture
def ran():
    calls = []

    @tool("t_comum", "Comum.", {"x": {"type": "string"}})
    def comum(x, ctx=None):
        calls.append(("comum", x)); return "feito " + x

    @tool("t_perigosa", "Perigosa.", {"x": {"type": "string"}}, dangerous=True)
    def perigosa(x, ctx=None):
        calls.append(("perigosa", x)); return "apagado " + x

    yield calls
    registry._REG.pop("t_comum"); registry._REG.pop("t_perigosa")


def make(owner=True, enrolled=True):
    told, clock = [], Clock()
    gate = Gate(CFG, Context(CFG), FakeSpeaker(owner, enrolled), FakeAudit(), told.append, clock, spawn=lambda job: job())
    return gate, told, clock


def test_common_tool_runs_immediately(ran):
    gate, told, _ = make()
    assert gate.submit("t_comum", {"x": "a"}) == "feito a"
    assert ran == [("comum", "a")] and gate.pending is None


def test_dangerous_tool_waits_for_confirmation(ran):
    gate, told, _ = make()
    out = gate.submit("t_perigosa", {"x": "a"})
    assert out.startswith("pendente") and ran == []
    assert gate.pending["name"] == "t_perigosa" and gate.pending["args"] == {"x": "a"}


def test_spoken_yes_with_owner_voice_executes_and_notifies(ran):
    gate, told, _ = make(owner=True)
    gate.submit("t_perigosa", {"x": "a"})
    gate.on_user_utterance("Sim, pode fazer.", AUDIO)
    assert ran == [("perigosa", "a")] and gate.pending is None
    assert len(told) == 1 and "apagado a" in told[0]


def test_spoken_yes_with_unknown_voice_keeps_pending(ran):
    gate, told, _ = make(owner=False)
    gate.submit("t_perigosa", {"x": "a"})
    gate.on_user_utterance("sim", AUDIO)
    assert ran == [] and gate.pending is not None
    assert len(told) == 1 and "NÃO foi executada" in told[0] and "clicar em Sim" in told[0]


def test_confirmation_closes_card_before_running_in_background(ran, monkeypatch):
    from viv.bus import BUS
    events, jobs = [], []
    monkeypatch.setattr(BUS, "emit", lambda channel, text="", **extra: events.append(channel))
    gate, told, _ = make()
    gate.spawn = jobs.append
    gate.submit("t_perigosa", {"x": "a"})
    gate.on_user_utterance("sim", AUDIO)
    assert "confirm_done" in events and ran == [] and gate.pending is None, "o cartão fecha antes de a ação rodar"
    jobs[0]()
    assert ran == [("perigosa", "a")] and "apagado a" in told[-1]


def test_model_repeating_confirmed_request_does_not_ask_or_run_again(ran):
    gate, told, clock = make()
    gate.submit("t_perigosa", {"x": "a"})
    assert gate.submit("t_perigosa", {"x": "a"}).startswith("pendente: este mesmo pedido já está na tela")
    gate.on_user_utterance("sim", AUDIO)
    again = gate.submit("t_perigosa", {"x": "a"})
    assert gate.pending is None and ran == [("perigosa", "a")] and "já foi executado" in again and "apagado a" in again
    assert gate.submit("t_perigosa", {"x": "b"}).startswith("pendente"), "outro pedido abre o cartão normalmente"
    gate.on_click(False)
    clock.now += 60
    assert gate.submit("t_perigosa", {"x": "a"}).startswith("pendente"), "pedir de novo depois de um tempo vale"


def test_failed_action_can_be_requested_again(ran):
    gate, told, _ = make()
    gate.submit("t_perigosa", {"x": "a"})
    gate.on_click(True)
    gate.last["result"] = "erro: falta conectar"
    assert gate.submit("t_perigosa", {"x": "a"}).startswith("pendente")


def test_repeat_while_confirmed_action_still_runs(ran):
    gate, told, _ = make()
    gate.spawn = lambda job: None                 # a ação confirmada ainda não terminou
    gate.submit("t_perigosa", {"x": "a"})
    gate.on_click(True)
    assert "está sendo executado" in gate.submit("t_perigosa", {"x": "a"}) and ran == []


@pytest.mark.parametrize("owner,enrolled", [(False, True), (False, False)])
def test_click_yes_executes_without_biometrics(ran, owner, enrolled):
    gate, told, _ = make(owner=owner, enrolled=enrolled)
    gate.submit("t_perigosa", {"x": "a"})
    gate.on_click(True)
    assert ran == [("perigosa", "a")] and "apagado a" in told[0]


@pytest.mark.parametrize("phrase", ["não", "Cancela isso", "sim, não, cancela", "deixa pra lá"])
def test_spoken_denial_cancels(ran, phrase):
    gate, told, _ = make()
    gate.submit("t_perigosa", {"x": "a"})
    gate.on_user_utterance(phrase, AUDIO)
    assert ran == [] and gate.pending is None and "cancelada" in told[0].lower()


def test_click_no_cancels(ran):
    gate, told, _ = make()
    gate.submit("t_perigosa", {"x": "a"})
    gate.on_click(False)
    assert ran == [] and gate.pending is None


def test_unrelated_speech_changes_nothing(ran):
    gate, told, _ = make()
    gate.submit("t_perigosa", {"x": "a"})
    gate.on_user_utterance("que horas são? simples assim", AUDIO)
    assert ran == [] and gate.pending is not None and told == []


def test_timeout_cancels_only_after_30_seconds(ran):
    gate, told, clock = make()
    gate.submit("t_perigosa", {"x": "a"})
    clock.now = 29.0; gate.tick()
    assert gate.pending is not None
    clock.now = 30.5; gate.tick()
    assert gate.pending is None and ran == [] and len(told) == 1


def test_second_dangerous_request_waits_its_turn_instead_of_being_refused(ran):
    gate, told, clock = make()
    gate.submit("t_perigosa", {"x": "a"})
    assert gate.submit("t_perigosa", {"x": "b"}).startswith("pendente: há outra confirmação na tela")
    assert gate.submit("t_perigosa", {"x": "b"}).startswith("pendente: este mesmo pedido já está na fila")
    clock.now = 20.0
    gate.on_click(True)
    assert ran == [("perigosa", "a")] and gate.pending["args"] == {"x": "b"}
    assert gate.pending["expires"] == 50.0                 # o prazo da segunda começa quando ela aparece
    gate.on_click(False)
    assert ran == [("perigosa", "a")] and gate.pending is None and gate.waiting == []


def test_queue_of_confirmations_has_a_limit_and_expiry_moves_it_on(ran):
    gate, told, clock = make()
    for x in "abcd":
        gate.submit("t_perigosa", {"x": x})
    assert gate.submit("t_perigosa", {"x": "e"}).startswith("recusado")
    clock.now = 31.0
    gate.tick()                                             # a primeira venceu: a segunda entra
    assert gate.pending["args"] == {"x": "b"} and ran == []


def test_yes_and_click_without_pending_do_nothing(ran):
    gate, told, _ = make()
    gate.on_user_utterance("sim", AUDIO); gate.on_click(True); gate.tick()
    assert ran == [] and told == []


def test_no_registered_tool_can_confirm():
    registry.load_all()
    assert not [d["name"] for d in registry.declarations() if "confirm" in d["name"]]


class FakeTasks:
    def __init__(self):
        self.calls = []

    def run(self, name, args, call, title="", group=""):
        self.calls.append((name, args))
        return call()


def test_common_tool_runs_through_tasks(ran):
    gate, _, _ = make()
    gate.tasks = FakeTasks()
    assert gate.submit("t_comum", {"x": "a"}) == "feito a"
    assert gate.tasks.calls == [("t_comum", {"x": "a"})]


def test_dangerous_tool_reaches_tasks_only_after_confirmation(ran):
    gate, _, _ = make()
    gate.tasks = FakeTasks()
    assert gate.submit("t_perigosa", {"x": "a"}).startswith("pendente")
    assert gate.tasks.calls == [] and ran == []
    gate.on_click(True)
    assert gate.tasks.calls == [("t_perigosa", {"x": "a"})] and ran == [("perigosa", "a")]
