"""Content-free stage timings. Durations may nest; do not sum every field."""
import contextvars
from contextlib import contextmanager
from collections import deque
import json
import math
from pathlib import Path
import time
import uuid
import psutil
from core.bus import BUS

STAGES = ('wake_whisper_ms', 'capture_ms', 'speaker_ms', 'whisper_ms', 'gemini_ms', 'tools_ms',
          'search_ms', 'tts_generate_ms', 'tts_decode_ms', 'tts_playback_ms')
CURRENT = contextvars.ContextVar('viv_trace', default=None)


class TurnTrace:
    def __init__(self, start=None):
        self.start = time.perf_counter() if start is None else start
        self.data = {'turn_id': uuid.uuid4().hex[:12], 'status': 'ok'}
        self.capture_end = None

    @contextmanager
    def activate(self):
        token = CURRENT.set(self)
        try:
            yield self
        finally:
            CURRENT.reset(token)

    def first_playback(self):
        now = time.perf_counter()
        self.data.setdefault('playback_start_ms', (now - self.start) * 1000)
        if self.capture_end is not None:
            self.data.setdefault('response_start_ms', (now - self.capture_end) * 1000)

    def finish(self, status='ok'):
        self.data['status'] = status
        self.data['total_ms'] = (time.perf_counter() - self.start) * 1000
        return dict(self.data)


@contextmanager
def measure(stage):
    if stage not in STAGES:
        raise ValueError('Unknown timing stage')
    trace = CURRENT.get()
    start = time.perf_counter()
    try:
        yield
    finally:
        if trace is not None:
            duration = (time.perf_counter() - start) * 1000
            trace.data[stage] = trace.data.get(stage, 0.0) + duration
            key = stage.replace('_ms', '_calls')
            trace.data[key] = trace.data.get(key, 0) + 1
            if stage == 'capture_ms':
                trace.capture_end = time.perf_counter()
            BUS.emit('stage', '', stage=stage, duration_ms=round(duration, 2))


def playback_started():
    trace = CURRENT.get()
    if trace is not None:
        trace.first_playback()


class Metrics:
    def __init__(self, cfg):
        self.log_path = cfg.get('metrics', {}).get('log_path', 'data/latency-v1.1.jsonl')
        self.recent = deque(maxlen=50)
        self.process = psutil.Process()

    def sample(self):
        mem = psutil.virtual_memory()
        result = {'process_ram_gb': self.process.memory_info().rss / 1024**3,
                  'system_ram_used_gb': mem.used / 1024**3,
                  'system_ram_total_gb': mem.total / 1024**3}
        BUS.emit('res', '', **result)
        return result

    def record(self, turn):
        # Allowlist: no transcript, tool arguments, raw exception or credentials.
        numeric = set(STAGES) | {s.replace('_ms', '_calls') for s in STAGES}
        numeric |= {'playback_start_ms', 'response_start_ms', 'total_ms'}
        clean = {k: round(v, 2) for k, v in turn.items()
                 if k in numeric and isinstance(v, (int, float)) and math.isfinite(v)}
        ident = str(turn.get('turn_id', ''))
        if len(ident) == 12 and all(c in '0123456789abcdef' for c in ident):
            clean['turn_id'] = ident
        clean['status'] = turn.get('status') if turn.get('status') in ('ok', 'error', 'empty', 'wake_ignored') else 'error'
        clean['ts'] = time.time()
        clean.update(self.sample())
        self.recent.append(clean)
        Path(self.log_path).parent.mkdir(parents=True, exist_ok=True)
        with open(self.log_path, 'a', encoding='utf-8') as f:
            f.write(json.dumps(clean) + '\n')
        BUS.emit('perf', 'Tempos do turno disponíveis', **clean)
        return clean
