"""Native fault trace only: no environment, locals, transcripts or credentials."""
import faulthandler
from datetime import datetime
from pathlib import Path

_HANDLE = None

def enable(root):
    global _HANDLE
    if _HANDLE is not None:
        return
    folder = Path(root) / 'data'
    folder.mkdir(exist_ok=True)
    _HANDLE = (folder / 'native-crash.log').open('a', encoding='utf-8', buffering=1)
    _HANDLE.write('\nInicializa??o: '+datetime.now().isoformat(timespec='seconds')+'\n')
    faulthandler.enable(file=_HANDLE, all_threads=True)


def stage(label):
    # Only constant stage labels; never pass exceptions or user content here.
    print('[Viv] '+label, flush=True)
    if _HANDLE is not None:
        _HANDLE.write('[Viv] '+label+'\n')


def failure(exc):
    """Stack location only: no exception message, source text or local variables."""
    import traceback
    frames = traceback.extract_tb(exc.__traceback__)
    lines = [type(exc).__name__] + [f'{Path(f.filename).name}:{f.lineno} {f.name}' for f in frames]
    text = ' | '.join(lines)
    print('[Viv] Falha no ciclo de voz: '+text, flush=True)
    if _HANDLE is not None:
        _HANDLE.write('[Viv] Falha no ciclo de voz: '+text+'\n')
