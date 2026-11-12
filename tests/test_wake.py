import numpy as np
import pytest

from viv.wake import ClapDetector, NameSpotter, WakeWatcher, matches_name

RATE, FRAME = 16000, 320
RNG = np.random.default_rng(7)


def silence(ms):
    return [np.zeros(FRAME, dtype=np.int16).tobytes() for _ in range(ms // 20)]


def noise_burst(ms=20, amp=0.5):
    return [(RNG.uniform(-amp, amp, FRAME) * 32767).astype(np.int16).tobytes() for _ in range(ms // 20)]


def voiced(ms, amp=0.3, hz=200):
    n = RATE * ms // 1000
    wave = (np.sin(2 * np.pi * hz * np.arange(n) / RATE) * amp * 32767).astype(np.int16)
    return [wave[i:i + FRAME].tobytes() for i in range(0, n, FRAME)]


def feed(detector, frames, start=0.0):
    fired, now = 0, start
    for f in frames:
        fired += bool(detector.feed(f, now))
        now += 0.02
    return fired


def claps(gap_ms):
    return silence(400) + noise_burst() + silence(gap_ms) + noise_burst() + silence(400)


def test_two_claps_300ms_apart_fire_once():
    assert feed(ClapDetector(), claps(300)) == 1


def test_single_clap_does_not_fire():
    assert feed(ClapDetector(), silence(400) + noise_burst() + silence(1500)) == 0


@pytest.mark.parametrize("gap_ms", [40, 1000])
def test_claps_too_close_or_too_far_do_not_fire(gap_ms):
    assert feed(ClapDetector(), claps(gap_ms)) == 0


def test_continuous_voice_does_not_fire_clap():
    assert feed(ClapDetector(), silence(400) + voiced(3000) + silence(400)) == 0


@pytest.mark.parametrize("text", ["Ei, Viv!", "vivi abre o chrome", "VIVE", "ei  viv."])
def test_matches_name_accepts_aliases(text):
    assert matches_name(text, ["Viv", "Vivi", "Vive"]) is True


@pytest.mark.parametrize("text", ["vou viver", "vivendo e aprendendo", "", "   ", "revive"])
def test_matches_name_rejects_other_words(text):
    assert matches_name(text, ["Viv", "Vivi", "Vive"]) is False


def spotter(reply="ei viv"):
    calls = []

    def transcribe(audio):
        calls.append(len(audio)); return reply
    return NameSpotter(["Viv", "Vivi", "Vive"], transcribe), calls


def test_name_spotter_fires_on_short_utterance():
    s, calls = spotter()
    assert feed(s, silence(400) + voiced(1000) + silence(600)) == 1
    assert len(calls) == 1 and 0.9 * RATE <= calls[0] <= 1.6 * RATE


def test_name_spotter_ignores_other_speech():
    s, calls = spotter("que horas são")
    assert feed(s, silence(400) + voiced(1000) + silence(600)) == 0 and len(calls) == 1


def test_name_spotter_never_transcribes_silence_or_blips():
    s, calls = spotter()
    assert feed(s, silence(2000) + voiced(100) + silence(1000)) == 0 and calls == []


def test_name_spotter_caps_segment_at_three_seconds():
    s, calls = spotter()
    feed(s, silence(400) + voiced(5000) + silence(600))
    assert calls and max(calls) <= 3 * RATE


def test_name_spotter_survives_transcriber_error():
    def boom(audio):
        raise RuntimeError("modelo ausente")
    s = NameSpotter(["Viv"], boom)
    assert feed(s, silence(400) + voiced(1000) + silence(600)) == 0


class FakeAudio:
    def __init__(self, frames):
        self.frames = list(frames)

    def read(self, timeout=0.1):
        return self.frames.pop(0) if self.frames else None


def test_watcher_reports_clap_once():
    reasons = []
    cfg = {"wake": {"clap_enabled": True, "name_enabled": False, "clap_min_gap_ms": 120, "clap_max_gap_ms": 700,
                    "aliases": ["Viv"]}}
    frames = claps(300)
    w = WakeWatcher(cfg, FakeAudio(frames), reasons.append)
    for _ in range(len(frames) + 5):
        w.run_once()
    assert reasons == ["clap"]


def test_watcher_reports_name():
    reasons = []
    cfg = {"wake": {"clap_enabled": False, "name_enabled": True, "aliases": ["Viv"]}}
    frames = silence(400) + voiced(1000) + silence(600)
    w = WakeWatcher(cfg, FakeAudio(frames), reasons.append, transcribe=lambda audio: "ei, viv")
    for _ in range(len(frames)):
        w.run_once()
    assert reasons == ["name"]
