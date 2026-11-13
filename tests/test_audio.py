import numpy as np
import pytest

from viv.audio import AudioIO, echo_gate, resolve_input, rms

DEVICES = [
    {"index": 0, "name": "Alto-falantes (Realtek)", "max_input_channels": 0},
    {"index": 1, "name": "Microfone (USB Microphone)", "max_input_channels": 1},
    {"index": 2, "name": "Microfone (Realtek Audio)", "max_input_channels": 2},
    {"index": 3, "name": "USB Microphone saída", "max_input_channels": 0},
]
CFG = {"audio": {"input_device_name": None, "headphones": False, "barge_in_rms": 0.08}}


class Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


def frame(value: int, n: int = 320) -> bytes:
    return (np.ones(n, dtype=np.int16) * value).tobytes()


def test_resolve_input_exact_name():
    assert resolve_input(DEVICES, "Microfone (Realtek Audio)") == 2


def test_resolve_input_substring_case_insensitive_and_inputs_only():
    assert resolve_input(DEVICES, "usb microphone") == 1


@pytest.mark.parametrize("devices,name", [(DEVICES, "Blue Yeti"), (DEVICES, None), (DEVICES, ""), ([], "USB")])
def test_resolve_input_falls_back_to_default(devices, name):
    assert resolve_input(devices, name) is None


def test_rms_of_silence_and_full_scale():
    assert rms(frame(0)) == 0.0
    assert rms(frame(32767)) == pytest.approx(1.0, abs=0.01)
    assert rms(b"") == 0.0


def test_echo_gate():
    assert echo_gate(0.0, playing=False, headphones=True, threshold=0.08) is True
    assert echo_gate(0.01, playing=True, headphones=True, threshold=0.08) is False   # vazamento do fone
    assert echo_gate(0.03, playing=True, headphones=True, threshold=0.08) is True
    assert echo_gate(0.0, playing=False, headphones=False, threshold=0.08) is True
    assert echo_gate(0.05, playing=True, headphones=False, threshold=0.08) is False
    assert echo_gate(0.20, playing=True, headphones=False, threshold=0.08) is True


def test_play_then_flush_outputs_silence():
    audio = AudioIO(CFG, clock=Clock())
    audio.play(frame(1000, 4800))
    audio.flush()
    out = bytearray(960)
    audio._on_output(out, 480, None, None)
    assert bytes(out) == bytes(960)


def test_output_callback_plays_queued_audio_then_pads_with_silence():
    audio = AudioIO(CFG, clock=Clock())
    audio.play(frame(1000, 240))
    out = bytearray(960)
    audio._on_output(out, 480, None, None)
    samples = np.frombuffer(bytes(out), dtype=np.int16)
    assert (samples[:240] == 1000).all() and (samples[240:] == 0).all()


def test_is_playing_holds_for_600ms_after_buffer_empties():
    clock = Clock()
    audio = AudioIO(CFG, clock=clock)
    assert audio.is_playing() is False
    audio.play(frame(1000, 480))
    assert audio.is_playing() is True
    audio._on_output(bytearray(960), 480, None, None)
    clock.now += 0.5
    assert audio.is_playing() is True
    clock.now += 0.2
    assert audio.is_playing() is False


def test_input_callback_feeds_read_and_recent_buffer():
    audio = AudioIO(CFG, clock=Clock())
    audio._on_input(frame(3277), 320, None, None)
    assert audio.read(timeout=0.01) == frame(3277)
    assert audio.read(timeout=0.01) is None
    recent = audio.recent(6.0)
    assert recent.dtype == np.float32 and len(recent) == 320 and recent[0] == pytest.approx(0.1, abs=0.001)


def test_recent_keeps_only_last_six_seconds():
    audio = AudioIO(CFG, clock=Clock())
    for i in range(400):  # 8 s
        audio._on_input(frame(i), 320, None, None)
    recent = audio.recent(6.0)
    assert len(recent) == 96000
    assert recent[-1] == pytest.approx(399 / 32768, abs=1e-6)
    assert len(audio.recent(1.0)) == 16000


def test_should_send_blocks_quiet_mic_while_playing():
    audio = AudioIO(CFG, clock=Clock())
    assert audio.should_send(frame(100)) is True
    audio.play(frame(1000, 480))
    assert audio.should_send(frame(100)) is False
    assert audio.should_send(frame(20000)) is False      # um estalo isolado não abre o microfone
    assert audio.should_send(frame(100)) is False


def test_should_send_opens_on_sustained_speech_and_holds_through_pauses():
    clock = Clock()
    audio = AudioIO(CFG, clock=clock)
    audio.play(frame(1000, 48000))
    assert [audio.should_send(frame(20000)) for _ in range(3)] == [False, False, False]   # começo da fala: só mede o eco
    audio._echo = 0.0
    clock.now += 0.5
    assert [audio.should_send(frame(20000)) for _ in range(3)] == [False, False, True]
    clock.now += 0.3
    assert audio.should_send(frame(100)) is True         # pausa curta dentro da frase continua passando
    clock.now += 0.7
    assert audio.should_send(frame(100)) is False        # depois de HOLD em silêncio, fecha de novo


def test_should_send_with_headphones_blocks_only_faint_leak():
    audio = AudioIO({"audio": {"headphones": True, "barge_in_rms": 0.08}}, clock=Clock())
    audio.play(frame(1000, 48000))
    assert [audio.should_send(frame(200)) for _ in range(4)] == [False] * 4
    assert [audio.should_send(frame(2000)) for _ in range(3)] == [False, False, True]


def test_full_input_queue_drops_oldest_instead_of_blocking():
    audio = AudioIO(CFG, clock=Clock())
    for i in range(2000):
        audio._on_input(frame(i), 320, None, None)
    first = np.frombuffer(audio.read(timeout=0.01), dtype=np.int16)[0]
    assert first > 0
