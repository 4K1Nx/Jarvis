import threading

import pytest

from viv import tasks as tasks_module
from viv.bus import BUS
from viv.tasks import Tasks

WAIT = 2.0


@pytest.fixture(autouse=True)
def quiet_bus(monkeypatch):
    events = []
    monkeypatch.setattr(BUS, "emit", lambda channel, text="", **extra: events.append((channel, text, extra)))
    return events


class Done:
    """Coleta os avisos de fim e deixa o teste esperar por eles."""
    def __init__(self):
        self.items, self._event = [], threading.Event()

    def __call__(self, task):
        self.items.append(task)
        self._event.set()

    def wait(self, count=1):
        for _ in range(200):
            if len(self.items) >= count:
                return self.items
            self._event.wait(0.01)
            self._event.clear()
        raise AssertionError(f"esperava {count} aviso(s), vieram {len(self.items)}")


def slow(release, result="feito", started=None):
    def call():
        if started is not None:
            started.set()
        assert release.wait(WAIT)
        return result
    return call


def test_fast_call_returns_result():
    done = Done()
    tasks = Tasks(after=0.5, on_done=done)
    assert tasks.run("t", {}, lambda: "ok") == "ok"
    assert done.items == [] and tasks.snapshot() == []


def test_slow_call_goes_to_background():
    done, release = Done(), threading.Event()
    tasks = Tasks(after=0.05, on_done=done)
    result = tasks.run("t", {}, slow(release), title="Título")
    assert result.startswith("em segundo plano: tarefa 1 (Título)")
    assert tasks.snapshot()[0]["status"] == "rodando"
    release.set()
    task = done.wait()[0]
    assert task["status"] == "pronta" and task["result"] == "feito"
    assert tasks.snapshot()[0]["status"] == "pronta"


def test_duplicate_while_running():
    done, release, runs = Done(), threading.Event(), []

    def call():
        runs.append(1)
        assert release.wait(WAIT)
        return "feito"
    tasks = Tasks(after=0.05, on_done=done)
    tasks.run("t", {"x": 1}, call)
    assert tasks.run("t", {"x": 1}, call).startswith("já está rodando")
    release.set()
    done.wait()
    assert runs == [1]


def test_same_group_runs_one_at_a_time():
    done, first, second, started = Done(), threading.Event(), threading.Event(), threading.Event()
    tasks = Tasks(after=0.05, on_done=done)
    tasks.run("a", {}, slow(first), group="browser")
    tasks.run("b", {}, slow(second, started=started), group="browser")
    assert not started.is_set()               # a segunda espera a vez
    first.set()
    assert started.wait(WAIT)
    second.set()
    done.wait(2)


def test_note_goes_to_the_right_task():
    done, release, noted = Done(), threading.Event(), threading.Event()

    def call():
        tasks_module.note("Etapa 1", None)
        assert release.wait(WAIT)             # já no fundo
        handled = tasks_module.note("Etapa 2", 0.5)
        noted.set()
        assert release2.wait(WAIT)
        return str(handled)
    release2 = threading.Event()
    tasks = Tasks(after=0.05, on_done=done)
    tasks.run("t", {}, call)
    release.set()
    assert noted.wait(WAIT)
    shot = tasks.snapshot()[0]
    assert shot["step"] == "Etapa 2" and shot["value"] == 0.5
    release2.set()
    assert done.wait()[0]["result"] == "True"
    assert tasks_module.note("fora", None) is False and tasks_module.backgrounded() is False


def test_failure_in_background_is_reported():
    done, release = Done(), threading.Event()

    def call():
        assert release.wait(WAIT)
        raise RuntimeError("quebrou")
    tasks = Tasks(after=0.05, on_done=done)
    tasks.run("t", {}, call)
    release.set()
    task = done.wait()[0]
    assert task["status"] == "falhou" and "quebrou" in task["result"]


def test_error_result_counts_as_failure():
    done, release = Done(), threading.Event()
    tasks = Tasks(after=0.05, on_done=done)
    tasks.run("t", {}, slow(release, result="erro: sem rede"))
    release.set()
    assert done.wait()[0]["status"] == "falhou"


def test_long_result_is_cut():
    done, release = Done(), threading.Event()
    tasks = Tasks(after=0.05, on_done=done)
    tasks.run("t", {}, slow(release, result="x" * 5000))
    release.set()
    assert len(done.wait()[0]["result"]) <= 2000


def test_history_keeps_20():
    done = Done()
    tasks = Tasks(after=0.01, on_done=done)
    for i in range(25):
        release = threading.Event()
        tasks.run("t", {"i": i}, slow(release))
        release.set()
        done.wait(i + 1)
    assert len(tasks.snapshot()) == 20


def test_background_emits_tasks_event_and_hides_the_bar(quiet_bus):
    done, release = Done(), threading.Event()
    tasks = Tasks(after=0.05, on_done=done)
    tasks.run("t", {}, slow(release), title="Título")
    listed = [e for e in quiet_bus if e[0] == "tasks"]
    assert listed and listed[-1][2]["items"][0]["title"] == "Título"
    assert any(e[0] == "progress" and e[2].get("done") for e in quiet_bus)
    release.set()
    done.wait()
    assert [e for e in quiet_bus if e[0] == "tasks"][-1][2]["items"] == []
