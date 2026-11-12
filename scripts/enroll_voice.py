"""Cadastro local da voz. Não acessa o Gemini, o .env nem as ferramentas do PC.

Uso: .venv\\Scripts\\python.exe scripts\\enroll_voice.py  (com a Viv fechada)
"""
import argparse
import shutil
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

PHRASES = [
    "Oi, Viv. Hoje estou cadastrando minha voz com calma.",
    "Esta frase serve apenas para reconhecer a minha voz.",
    "Gosto de conversar usando meu tom natural, sem pressa.",
    "A minha assistente se chama Viv e fala em português.",
    "Agora vou falar perto do microfone, como no dia a dia.",
    "Posso fazer perguntas e continuar a mesma conversa.",
    "Quero ouvir respostas claras e gentis durante o dia.",
    "Esta é a última frase do meu cadastro de voz.",
]


def validate_clip(audio, rate=16000):
    samples = np.asarray(audio, dtype=np.float32).reshape(-1)
    if len(samples) < rate * 2 or not np.isfinite(samples).all():
        raise ValueError("Use pelo menos dois segundos de áudio válido.")
    if np.sqrt(np.mean(samples ** 2)) < .001:
        raise ValueError("Sinal muito baixo. Aproxime-se do microfone e tente novamente.")
    if np.mean(np.abs(samples) >= .99) > .01:
        raise ValueError("Áudio saturado. Reduza o ganho antes de cadastrar.")
    return samples


def record(seconds, device):
    import sounddevice as sd
    audio = sd.rec(int(seconds * 16000), samplerate=16000, channels=1, dtype="float32", device=device)
    sd.wait()
    return validate_clip(audio.flatten())


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--owner", help="Seu nome, não o nome da assistente")
    ap.add_argument("--seconds", type=float, default=5)
    args = ap.parse_args()
    if not 3 <= args.seconds <= 15:
        ap.error("Use entre 3 e 15 segundos por frase.")
    cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    path = Path(cfg["speaker_id"]["voiceprint_path"])
    if not path.is_absolute():
        path = ROOT / path
    cfg["speaker_id"]["voiceprint_path"] = str(path)
    if path.exists():
        print("Já existe cadastro. Uma cópia será preservada antes da substituição.")
        if input("Digite SUBSTITUIR para refazer, ou Enter para cancelar: ").strip() != "SUBSTITUIR":
            print("Cancelado. Cadastro preservado.")
            return
    owner = (args.owner or input("Seu nome (proprietário): ")).strip()
    if not owner:
        ap.error("Informe seu nome.")

    import sounddevice as sd
    from viv.audio import resolve_input
    from viv.speaker import Speaker
    device = resolve_input([dict(d) for d in sd.query_devices()], cfg.get("audio", {}).get("input_device_name"))
    name = sd.query_devices(device if device is not None else sd.default.device[0])["name"]
    print("Microfone: " + name)
    print("Feche a Viv antes de gravar. Nenhuma frase executa comandos.")
    speaker = Speaker(cfg)
    clips = []
    for index in range(max(3, cfg["speaker_id"].get("enroll_clips", 8))):
        while True:
            input(f"[{index + 1}] Aperte Enter e leia: " + PHRASES[index % len(PHRASES)])
            try:
                clips.append(record(args.seconds, device))
                break
            except ValueError as exc:
                print(str(exc))
        print("Frase capturada.")
    if path.exists():
        backup = path.with_name(path.name + ".backup-" + datetime.now().strftime("%Y%m%d-%H%M%S"))
        shutil.copy2(path, backup)
    speaker.enroll(clips, owner)
    print("Cadastro salvo. Inicie a Viv de novo com run.bat.")
    print("Áudio bruto não foi salvo; só o vetor da voz.")


if __name__ == "__main__":
    main()
