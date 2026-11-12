"""Dublês de teste com os mesmos nomes de campo e método do SDK google-genai (Live API)."""
import asyncio
import time
from contextlib import asynccontextmanager
from types import SimpleNamespace as NS

import numpy as np


def msg(data=None, interrupted=False, input_text=None, input_finished=None, output_text=None,
        turn_complete=False, tool_calls=None, go_away=False, handle=None):
    """Mensagem do servidor. tool_calls: lista de (id, nome, args)."""
    content = None
    if interrupted or input_text is not None or output_text is not None or turn_complete:
        content = NS(
            interrupted=interrupted or None,
            turn_complete=turn_complete or None,
            input_transcription=NS(text=input_text, finished=input_finished) if input_text is not None else None,
            output_transcription=NS(text=output_text, finished=None) if output_text is not None else None)
    return NS(
        data=data, server_content=content,
        tool_call=NS(function_calls=[NS(id=i, name=n, args=a) for i, n, a in tool_calls]) if tool_calls else None,
        go_away=NS(time_left="5s") if go_away else None,
        session_resumption_update=NS(new_handle=handle, resumable=True) if handle else None)


class FakeSession:
    def __init__(self):
        self.inbox: asyncio.Queue = asyncio.Queue()
        self.sent_audio, self.sent_text, self.tool_responses = [], [], []

    def push(self, *messages):
        for m in messages:
            self.inbox.put_nowait(m)

    async def send_realtime_input(self, *, audio=None, text=None):
        if audio is not None:
            self.sent_audio.append(audio.data)
        if text is not None:
            self.sent_text.append(text)

    async def send_tool_response(self, *, function_responses):
        self.tool_responses += list(function_responses)

    async def receive(self):
        while True:
            m = await self.inbox.get()
            if isinstance(m, Exception):
                raise m
            yield m
            if m.server_content is not None and m.server_content.turn_complete:
                return


class FakeConnect:
    """connect(config) -> gerenciador de contexto assíncrono. `failures`: exceções das primeiras chamadas."""

    def __init__(self, failures=()):
        self.failures = list(failures)
        self.configs, self.sessions, self.closed = [], [], 0

    def __call__(self, config):
        @asynccontextmanager
        async def cm():
            self.configs.append(config)
            if self.failures:
                raise self.failures.pop(0)
            session = FakeSession()
            self.sessions.append(session)
            try:
                yield session
            finally:
                self.closed += 1
        return cm()

    @property
    def session(self):
        return self.sessions[-1]


class FakeAudio:
    input_name = "Microfone falso"

    def __init__(self):
        self.frames, self.played, self.beeps = [], [], []
        self.flushes = 0
        self.playing, self.send = False, True

    def read(self, timeout=0.1):
        if self.frames:
            return self.frames.pop(0)
        time.sleep(0.005)
        return None

    def play(self, pcm):
        self.played.append(pcm)

    def flush(self):
        self.flushes += 1

    def is_playing(self):
        return self.playing

    def should_send(self, frame):
        return self.send

    def recent(self, seconds=6.0):
        return np.zeros(16000, dtype=np.float32)

    def beep(self, kind):
        self.beeps.append(kind)


class FakeGate:
    def __init__(self):
        self.submitted, self.utterances, self.ticks = [], [], 0
        self.pending = None

    def submit(self, name, args):
        self.submitted.append((name, args))
        return "resultado de " + name

    def on_user_utterance(self, text, audio):
        self.utterances.append(text)

    def tick(self):
        self.ticks += 1


class FakeWatcher:
    def __init__(self):
        self.resets = 0

    def run_once(self):
        time.sleep(0.005)

    def reset(self):
        self.resets += 1


class FakeMemory:
    def __init__(self):
        self.turns = []

    def add_turn(self, role, text):
        self.turns.append((role, text))

    def prompt_block(self, n):
        return "O usuário gosta de café."


class FakeGaps:
    def __init__(self):
        self.codes = []

    def record(self, code):
        self.codes.append(code)


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now
