"""Summarize content-free Viv 1.1 latency logs; does not load the assistant."""
import json
import math
from pathlib import Path
import statistics
import sys

path = Path(sys.argv[1]) if len(sys.argv)>1 else Path(__file__).resolve().parents[1] / 'data/latency-v1.1.jsonl'
if not path.exists():
    raise SystemExit('Ainda não há métricas. Converse com a Viv e execute novamente.')
rows=[]
for line in path.read_text(encoding='utf-8').splitlines():
    try:
        rows.append(json.loads(line))
    except json.JSONDecodeError:
        pass
labels = {'capture_ms':'Captura/VAD', 'speaker_ms':'Biometria', 'whisper_ms':'Whisper',
          'gemini_ms':'Gemini', 'tools_ms':'Ferramentas', 'search_ms':'Busca',
          'tts_generate_ms':'Geração Edge TTS', 'tts_decode_ms':'Decodificação',
          'tts_playback_ms':'Reprodução', 'playback_start_ms':'Ativação até áudio',
          'response_start_ms':'Fim captura até áudio', 'total_ms':'Turno completo'}
print(f'{len(rows)} turnos; {sum(r.get("status")=="error" for r in rows)} com falha. Valores em ms.')
print(f'{"Etapa":<24} {"n":>4} {"mediana":>10} {"p95":>10} {"máximo":>10}')
for key,label in labels.items():
    values=sorted(r[key] for r in rows if isinstance(r.get(key),(int,float)) and math.isfinite(r[key]))
    if values:
        p95=values[max(0,math.ceil(.95*len(values))-1)]
        print(f'{label:<24} {len(values):4} {statistics.median(values):10.1f} {p95:10.1f} {max(values):10.1f}')
print('Busca está incluída em Ferramentas. Início do áudio é o retorno de sd.play, não uma medição acústica.')
