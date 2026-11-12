import subprocess
import sys

import yaml

import main
from tests.fakes import FakeAudio, FakeConnect
from viv.tools import registry


def cfg(tmp_path):
    c = yaml.safe_load(open("config.yaml", encoding="utf-8"))
    c["memory"]["path"] = str(tmp_path / "mem.json")
    c["reminders"]["path"] = str(tmp_path / "jobs.json")
    c["audit"]["path"] = str(tmp_path / "audit.jsonl")
    c["speaker_id"]["voiceprint_path"] = str(tmp_path / "voz.json")
    c["wake"]["name_enabled"] = False
    c["settings"] = {"path": str(tmp_path / "viv_config.json")}
    return c


def test_build_wires_everything_without_devices_or_network(tmp_path):
    parts = main.build(cfg(tmp_path), connect=FakeConnect(), audio=FakeAudio(), client=None)
    assert parts.viv.gate is parts.gate and parts.gate.ctx.memory is parts.memory
    assert parts.gate.ctx.reminders is parts.reminders
    assert parts.gate.notify == parts.viv.notify
    assert parts.reminders.notify.__self__ is parts.viv
    assert parts.app is not None and len(registry.declarations()) > 30


def test_reminder_text_is_delivered_as_reminder(tmp_path):
    parts = main.build(cfg(tmp_path), connect=FakeConnect(), audio=FakeAudio(), client=None)
    parts.reminders.schedule_in(60, "tomar água")
    parts.reminders.run_due(now=parts.reminders.pending()[0]["at"] + 1)
    assert parts.viv._outbox and "tomar água" in parts.viv._outbox[0] and "Lembrete" in parts.viv._outbox[0]


def test_hotkey_toggles_between_wake_and_sleep(tmp_path):
    parts = main.build(cfg(tmp_path), connect=FakeConnect(), audio=FakeAudio(), client=None)
    calls = []
    parts.viv.wake = lambda reason="": calls.append("wake")
    parts.viv.sleep = lambda: calls.append("sleep")
    main.toggle(parts.viv)
    parts.viv.state = main.State.LISTENING
    main.toggle(parts.viv)
    assert calls == ["wake", "sleep"]


def test_missing_key_makes_connect_raise_missing_key(tmp_path, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    client, connect = main.make_client(cfg(tmp_path))
    assert client is None
    try:
        connect({})
        raise AssertionError("deveria falhar")
    except main.MissingKey:
        pass


def test_demo_mode_does_not_import_sounddevice():
    code = ("import sys, main; main.build_demo(__import__('yaml').safe_load(open('config.yaml', encoding='utf-8')));"
            "print('sounddevice' in sys.modules)")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60)
    assert out.stdout.strip().endswith("False"), out.stderr[-500:]
