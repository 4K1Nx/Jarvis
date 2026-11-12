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
    gate = Gate(CFG, Context(CFG), FakeSpeaker(owner, enrolled), FakeAudit(), told.append, clock)
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
    assert ran == [] and gate.pending is not None and told == []


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


def test_second_dangerous_request_is_refused_and_first_kept(ran):
    gate, told, _ = make()
    gate.submit("t_perigosa", {"x": "a"})
    assert gate.submit("t_perigosa", {"x": "b"}).startswith("recusado")
    gate.on_click(True)
    assert ran == [("perigosa", "a")]


def test_yes_and_click_without_pending_do_nothing(ran):
    gate, told, _ = make()
    gate.on_user_utterance("sim", AUDIO); gate.on_click(True); gate.tick()
    assert ran == [] and told == []


def test_no_registered_tool_can_confirm():
    registry.load_all()
    assert not [d["name"] for d in registry.declarations() if "confirm" in d["name"]]
