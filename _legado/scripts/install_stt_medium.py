"""Explicit public model installation; never loads .env or uses an HF token."""
from pathlib import Path
from huggingface_hub import snapshot_download
ROOT=Path(__file__).resolve().parents[1]
if __name__=='__main__':
    snapshot_download('Systran/faster-whisper-medium', token=False,
        local_dir=str(ROOT/'models'/'faster-whisper-medium'),
        allow_patterns=['config.json','model.bin','tokenizer.json','vocabulary.*','preprocessor_config.json'])
    print('Whisper Medium instalado localmente.')
