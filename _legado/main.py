"""Viv entrypoint: python main.py (voice) or python main.py --hud (demo)."""
import argparse, asyncio, random, sys, threading, time, yaml, queue
from pathlib import Path
import os
os.chdir(Path(__file__).resolve().parent)
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass
from core.bus import BUS
from core.audit import Audit


def hud_only():
    import server
    def fake():
        time.sleep(1.5)
        script = [("wake", "Demonstração de ativação"),
                  ("state", "listening"), ("user", "Olá, Viv. Como você está?"),
                  ("state", "thinking"), ("llm", "Demonstração de processamento"),
                  ("state", "speaking"), ("tts", "Viv: Olá! Estou pronta para conversar com você."),
                  ("state", "idle")]
        while True:
            for ch, tx in script:
                BUS.emit(ch, tx, state=tx if ch == "state" else None)
                for _ in range(12):
                    BUS.emit("level", "", value=random.random() * 0.7)
                    time.sleep(0.05)
            time.sleep(2)
    threading.Thread(target=fake, daemon=True).start()
    server.start(None)


def full():
    import server
    from core.audio_in import AudioInput
    from core.wakeword import WakeWord
    from core.stt import STT
    from core.llm import LLM
    from core.tts import TTS
    from core.memory import Memory
    from core.speaker_id import SpeakerID
    from core.metrics import Metrics
    from core.orchestrator import Orchestrator
    from core.rag import DocRAG
    from core.learning import Learning
    from core.audit import Audit
    from core.proactive import Proactive
    import tools.assistant  # noqa: F401
    import tools.browser    # noqa: F401
    import tools.vision     # noqa: F401

    cfg = yaml.safe_load(open("config.yaml", encoding="utf-8"))
    print("· loading local speech models + Gemini agent tools…")
    tts = TTS(cfg)
    rag = DocRAG(cfg) if cfg.get("rag", {}).get("enabled", False) else None
    learning = Learning(cfg)
    audit = Audit(cfg)
    reminder_queue = queue.Queue()
    proactive = Proactive(cfg, speak=reminder_queue.put) if (cfg.get('reminders',{}).get('enabled',False) or cfg.get("proactive", {}).get("enabled", False)) else None
    try:
        stt = STT(cfg)
    except Exception as exc:
        raise RuntimeError("Whisper Small ausente ou incompatível. Consulte README_VIV.md para instalar o modelo explicitamente.") from exc
    orch = Orchestrator(cfg, AudioInput(cfg), WakeWord(cfg), stt, LLM(cfg), tts,
                        Memory(cfg), SpeakerID(cfg), Metrics(cfg),
                        rag=rag, learning=learning, proactive=proactive, audit=audit)
    orch.alerts = reminder_queue
    from core.capability_gaps import CapabilityGaps
    orch.gaps = CapabilityGaps()
    if cfg.get("assistant", {}).get("announce_gaps_on_start", False) and orch.gaps.count():
        reminder_queue.put('Tenho '+str(orch.gaps.count())+' pendências registradas. Pergunte: quais são suas pendências?')
    if rag and cfg.get("rag", {}).get("index_on_start"):
        threading.Thread(target=rag.index, daemon=True).start()
    for hhmm, line in ((cfg.get("proactive", {}).get("routines") or {}) if proactive and cfg.get("proactive",{}).get("enabled",False) else {}).items():
        proactive.schedule_daily(hhmm, line)
    print(f"· HUD → http://{cfg['server']['host']}:{cfg['server']['port']}")
    server.start(orch)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--hud", action="store_true", help="run the HUD with synthetic events only")
    a = p.parse_args()
    from core.startup_diagnostics import enable
    try:
        enable(Path(__file__).resolve().parent)
        hud_only() if a.hud else full()
    except KeyboardInterrupt:
        print("Viv encerrada.")
    except Exception as exc:
        print(f"Não foi possível iniciar a Viv: {exc}", file=sys.stderr)
        sys.exit(1)
