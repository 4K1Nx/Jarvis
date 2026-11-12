import json
import pytest
from viv.reminders import Reminders


def make(tmp_path, said):
    return Reminders(str(tmp_path / "jobs.json"), said.append)


def test_due_reminder_notifies_once_and_is_removed(tmp_path):
    said = []
    r = make(tmp_path, said)
    r.schedule_in(60, "tomar água")
    assert r.run_due(now=r.pending()[0]["at"] + 1) == 1
    assert said == ["tomar água"] and r.pending() == []
    assert r.run_due() == 0 and said == ["tomar água"]


def test_future_reminder_does_not_fire(tmp_path):
    said = []
    r = make(tmp_path, said)
    r.schedule_in(3600, "reunião")
    assert r.run_due() == 0 and said == [] and len(r.pending()) == 1


def test_reminders_persist_across_instances(tmp_path):
    make(tmp_path, []).schedule_in(3600, "reunião")
    assert [j["text"] for j in make(tmp_path, []).pending()] == ["reunião"]


@pytest.mark.parametrize("seconds,text", [(0, "x"), (-5, "x"), (float("nan"), "x"), (60, "  ")])
def test_invalid_reminder_is_rejected(tmp_path, seconds, text):
    with pytest.raises(ValueError):
        make(tmp_path, []).schedule_in(seconds, text)


def test_legacy_entries_are_kept_but_ignored(tmp_path):
    path = tmp_path / "jobs.json"
    legacy = {"at": 1.0, "text": "rotina antiga", "repeat_daily": True, "tool": None, "args": None}
    path.write_text(json.dumps([legacy]), encoding="utf-8")
    said = []
    r = Reminders(str(path), said.append)
    assert r.pending() == [] and r.run_due() == 0 and said == []
    r.schedule_in(60, "novo")
    assert legacy in json.loads(path.read_text(encoding="utf-8"))


def test_failed_delivery_keeps_reminder(tmp_path):
    def boom(_):
        raise RuntimeError("sem sessão")
    r = Reminders(str(tmp_path / "jobs.json"), boom)
    r.schedule_in(60, "x")
    assert r.run_due(now=r.pending()[0]["at"] + 1) == 0 and len(r.pending()) == 1
