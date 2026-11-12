import asyncio
import threading
from datetime import datetime

import pytest

from tests.fakes import Clock, FakeAudio, FakeConnect, FakeGaps, FakeGate, FakeMemory, FakeWatcher, msg
from viv.bus import BUS
from viv.live import MissingKey, State, Viv, build_config, classify
from viv.persona import system_instruction

CFG = {"assistant": {"name": "Viv", "idle_seconds": 60, "history_turns": 12},
       "live": {"model": "m", "voice": "Aoede", "language": "pt-BR"}, "safety": {"dangerous": []}}


class Env:
    def __init__(self, failures=()):
        self.audio, self.gate, self.memory = FakeAudio(), FakeGate(), FakeMemory()
        self.watcher, self.gaps, self.clock = FakeWatcher(), FakeGaps(), Clock()
        self.connect = FakeConnect(failures)
        self.naps, self.events = [], []

        async def nap(seconds):
            self.naps.append(seconds)
            await asyncio.sleep(0)
        self.viv = Viv(CFG, self.audio, self.gate, self.memory, self.watcher, self.connect,
                       gaps=self.gaps, clock=self.clock, nap=nap)

    def states(self):
        return [e[2].get("state") for e in self.events if e[0] == "state"]

    def cards(self):
        return [e for e in self.events if e[0] == "card"]


@pytest.fixture
async def env(monkeypatch, request):
    e = Env(getattr(request, "param", ()))
    monkeypatch.setattr(BUS, "emit", lambda channel, text="", **extra: e.events.append((channel, text, extra)))
    task = asyncio.create_task(e.viv.run())
    await asyncio.sleep(0.02)
    yield e
    task.cancel()
    try:
        await task
    except BaseException:
        pass


async def until(cond, timeout=2.0):
    end = asyncio.get_running_loop().time() + timeout
    while not cond():
        if asyncio.get_running_loop().time() > end:
            raise AssertionError("condição não atingida a tempo")
        await asyncio.sleep(0.01)


async def awake(e):
    e.viv.wake("button")
    await until(lambda: e.viv.state == State.LISTENING and e.connect.sessions)
    return e.connect.session


async def test_starts_sleeping_without_connecting(env):
    assert env.viv.state == State.SLEEPING and env.connect.configs == []


async def test_wake_opens_session_beeps_and_listens(env):
    await awake(env)
    assert len(env.connect.sessions) == 1 and env.audio.beeps == ["wake"]


async def test_simultaneous_wakes_open_one_session(env):
    threads = [threading.Thread(target=env.viv.wake, args=(r,)) for r in ("clap", "hotkey", "name")]
    for t in threads:
        t.start()
    await until(lambda: env.viv.state == State.LISTENING)
    env.viv.wake("button")
    await asyncio.sleep(0.1)
    assert len(env.connect.configs) == 1


async def test_audio_message_plays_and_turn_complete_returns_to_listening(env):
    s = await awake(env)
    s.push(msg(data=b"\x01\x02"))
    await until(lambda: env.viv.state == State.SPEAKING)
    assert env.audio.played == [b"\x01\x02"]
    s.push(msg(turn_complete=True))
    await until(lambda: env.viv.state == State.LISTENING)


async def test_stays_speaking_until_playback_ends(env):
    s = await awake(env)
    env.audio.playing = True
    s.push(msg(data=b"\x01\x02"), msg(turn_complete=True))
    await asyncio.sleep(0.3)
    assert env.viv.state == State.SPEAKING
    env.audio.playing = False
    await until(lambda: env.viv.state == State.LISTENING)


async def test_interruption_flushes_playback(env):
    s = await awake(env)
    s.push(msg(data=b"\x01\x02"), msg(interrupted=True))
    await until(lambda: env.audio.flushes == 1)
    await until(lambda: env.viv.state == State.LISTENING)


async def test_mic_frames_are_sent_and_gated_frames_become_silence(env):
    s = await awake(env)
    env.audio.frames.append(b"\x05\x00" * 320)
    await until(lambda: s.sent_audio == [b"\x05\x00" * 320])
    env.audio.send = False
    env.audio.frames.append(b"\x07\x00" * 320)
    await until(lambda: len(s.sent_audio) == 2)
    assert s.sent_audio[1] == bytes(640)


async def test_tool_call_goes_through_gate_and_is_answered_with_same_id(env):
    s = await awake(env)
    s.push(msg(tool_calls=[("id7", "desktop_launch_app", {"app": "notepad"})]))
    await until(lambda: s.tool_responses)
    assert env.gate.submitted == [("desktop_launch_app", {"app": "notepad"})]
    r = s.tool_responses[0]
    assert (r.id, r.name, r.response) == ("id7", "desktop_launch_app", {"result": "resultado de desktop_launch_app"})
    assert State.EXECUTING.value in env.states()


async def test_final_user_transcript_reaches_gate_and_memory(env):
    s = await awake(env)
    s.push(msg(input_text="abre o "), msg(input_text="chrome", input_finished=True))
    await until(lambda: env.gate.utterances == ["abre o chrome"])
    assert env.memory.turns == [("user", "abre o chrome")]
    finals = [e for e in env.events if e[0] == "transcript" and e[2].get("final") and e[2].get("role") == "user"]
    assert finals[-1][1] == "abre o chrome"


async def test_user_transcript_is_finalized_when_model_starts_answering(env):
    s = await awake(env)
    s.push(msg(input_text="que horas são"), msg(data=b"\x01\x02"))
    await until(lambda: env.gate.utterances == ["que horas são"])


async def test_viv_transcript_is_saved_on_turn_complete(env):
    s = await awake(env)
    s.push(msg(output_text="São "), msg(output_text="três horas."), msg(turn_complete=True))
    await until(lambda: ("viv", "São três horas.") in env.memory.turns)


async def test_sleeps_after_idle_timeout(env):
    await awake(env)
    env.clock.now += 61
    await until(lambda: env.viv.state == State.SLEEPING)
    assert env.connect.closed == 1 and env.audio.beeps[-1] == "sleep" and env.watcher.resets >= 1


async def test_activity_resets_idle_timer(env):
    s = await awake(env)
    env.clock.now += 50
    s.push(msg(input_text="oi", input_finished=True))
    await until(lambda: env.gate.utterances == ["oi"])
    env.clock.now += 20
    await asyncio.sleep(0.3)
    assert env.viv.state != State.SLEEPING


async def test_pending_confirmation_blocks_idle_sleep_and_ticks_gate(env):
    await awake(env)
    env.gate.pending = {"name": "fs_delete"}
    env.clock.now += 120
    await asyncio.sleep(0.3)
    assert env.viv.state != State.SLEEPING and env.gate.ticks > 0


@pytest.mark.parametrize("env", [(ConnectionError("queda"), ConnectionError("queda"))], indirect=True)
async def test_reconnects_with_growing_backoff(env):
    await awake(env)
    assert env.naps[:2] == [1, 2] and len(env.connect.configs) == 3
    assert any(e[0] == "state" and e[2].get("reconnecting") for e in env.events)


@pytest.mark.parametrize("env", [tuple(ConnectionError("queda") for _ in range(5))], indirect=True)
async def test_gives_up_after_five_failures(env):
    env.viv.wake("button")
    await until(lambda: State.ERROR.value in env.states())
    await until(lambda: env.viv.state == State.SLEEPING)
    assert len(env.connect.configs) == 5 and env.gaps.codes == ["conversation_error"]
    assert any("conex" in (c[1] + c[2].get("body", "")).lower() and c[2].get("ok") is False for c in env.cards())
    await asyncio.sleep(0.1)
    assert len(env.connect.configs) == 5


@pytest.mark.parametrize("env", [(MissingKey(),)], indirect=True)
async def test_missing_key_does_not_retry(env):
    env.viv.wake("button")
    await until(lambda: State.ERROR.value in env.states())
    await until(lambda: env.viv.state == State.SLEEPING)
    assert len(env.connect.configs) == 1
    assert any("Chave do Gemini ausente ou inválida" in c[1] + c[2].get("body", "") for c in env.cards())


@pytest.mark.parametrize("env", [(RuntimeError("429 RESOURCE_EXHAUSTED: quota exceeded"),)], indirect=True)
async def test_quota_error_warns_and_sleeps(env):
    env.viv.wake("button")
    await until(lambda: env.viv.state == State.SLEEPING and env.cards())
    assert len(env.connect.configs) == 1 and env.audio.beeps == ["error"]
    assert any("Cota do Gemini atingida" in c[1] + c[2].get("body", "") for c in env.cards())
    assert env.gaps.codes == ["gemini_quota"]


def test_classify_errors():
    assert classify(MissingKey()) == "auth"
    assert classify(RuntimeError("API key not valid. Please pass a valid API key.")) == "auth"
    assert classify(RuntimeError("1008 PERMISSION_DENIED")) == "auth"
    assert classify(RuntimeError("RESOURCE_EXHAUSTED")) == "quota"
    assert classify(ConnectionError("queda")) == "other"


async def test_go_away_reconnects_with_resumption_handle(env):
    s = await awake(env)
    s.push(msg(handle="h1"))
    s.push(msg(go_away=True))
    await until(lambda: len(env.connect.sessions) == 2)
    assert env.connect.configs[1]["session_resumption"] == {"handle": "h1"}
    assert env.viv.state != State.SLEEPING and env.audio.beeps == ["wake"]


async def test_dropped_connection_mid_session_reconnects(env):
    s = await awake(env)
    s.push(ConnectionError("caiu"))
    await until(lambda: len(env.connect.sessions) == 2)
    assert env.viv.state != State.SLEEPING


async def test_sleep_during_speech_flushes_and_closes(env):
    s = await awake(env)
    s.push(msg(data=b"\x01\x02"))
    await until(lambda: env.viv.state == State.SPEAKING)
    env.viv.sleep()
    await until(lambda: env.viv.state == State.SLEEPING)
    assert env.audio.flushes >= 1 and env.connect.closed == 1


async def test_viv_dormir_sleeps_only_after_farewell_turn(env):
    s = await awake(env)
    s.push(msg(tool_calls=[("id1", "viv_dormir", {})]))
    await until(lambda: s.tool_responses)
    assert env.gate.submitted == [] and env.viv.state != State.SLEEPING
    s.push(msg(data=b"\x01\x02"))
    await until(lambda: env.viv.state == State.SPEAKING)
    s.push(msg(turn_complete=True))
    await until(lambda: env.viv.state == State.SLEEPING)


async def test_notify_while_awake_sends_text_to_session(env):
    s = await awake(env)
    env.viv.notify("Ação confirmada. Resultado: ok")
    await until(lambda: s.sent_text)
    assert "Ação confirmada. Resultado: ok" in s.sent_text[0]


async def test_notify_while_sleeping_wakes_and_delivers(env):
    env.viv.notify("Lembrete: tomar água")
    await until(lambda: env.connect.sessions and env.connect.session.sent_text)
    assert "tomar água" in env.connect.session.sent_text[0]


def test_build_config_has_audio_transcription_tools_and_persona():
    cfg = build_config(CFG, FakeMemory(), handle=None)
    assert cfg["response_modalities"] == ["AUDIO"]
    assert cfg["speech_config"]["voice_config"]["prebuilt_voice_config"]["voice_name"] == "Aoede"
    assert cfg["speech_config"]["language_code"] == "pt-BR"
    assert "input_audio_transcription" in cfg and "output_audio_transcription" in cfg
    names = [d["name"] for d in cfg["tools"][0]["function_declarations"]]
    assert "viv_dormir" in names and "desktop_launch_app" in names
    assert "gosta de café" in cfg["system_instruction"]


def test_system_instruction_sets_persona_date_and_memory():
    text = system_instruction(CFG, FakeMemory(), datetime(2026, 11, 12, 15, 30))
    assert "Viv" in text and "português" in text and "12/11/2026" in text and "15:30" in text
    assert "gosta de café" in text and "pendente" in text


async def test_sleep_request_while_sleeping_does_not_cancel_next_wake(env):
    env.viv.sleep()
    await asyncio.sleep(0.05)
    await awake(env)
    await asyncio.sleep(0.3)
    assert env.viv.state == State.LISTENING and env.connect.closed == 0


async def test_long_running_tool_does_not_trigger_idle_sleep(env):
    s = await awake(env)
    release = threading.Event()

    def slow(name, args):
        release.wait(2)
        return "pronto"
    env.gate.submit = slow
    s.push(msg(tool_calls=[("id1", "browser_open", {"url": "x"})]))
    await until(lambda: env.viv.state == State.EXECUTING)
    env.clock.now += 120
    await asyncio.sleep(0.2)
    assert env.viv.state == State.EXECUTING
    release.set()
    await until(lambda: s.tool_responses)
