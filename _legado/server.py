"""FastAPI host: serves the WebGL HUD and streams pipeline events over a websocket."""
import asyncio, json, threading, time, yaml, os
from pathlib import Path
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import uvicorn

from core.bus import BUS
from core.audit import Audit

ROOT = Path(__file__).resolve().parent
with open(ROOT / "config.yaml", encoding="utf-8") as config_file:
    CFG = yaml.safe_load(config_file)
app = FastAPI(title="VIV 1.2")
app.mount("/static", StaticFiles(directory=ROOT / "web"), name="static")
ORCH = {"ref": None}
_voice_thread = None
_voice_lock = threading.Lock()
AUDIT = Audit(CFG)


@app.get("/")
def index():
    return FileResponse(ROOT / "web" / "index.html")


@app.get("/api/config")
def config():
    return {"llm": CFG["llm"]["model"], "stt": CFG["stt"]["model"], "tts": CFG["tts"]["engine"]}

@app.get("/api/status")
def status():
    o = ORCH["ref"]
    return {
        "gaps": o.gaps.summary() if o and getattr(o,"gaps",None) else "Nenhuma pendência registrada até agora.",
        "local_mode": CFG.get('assistant',{}).get('local_mode',False),
        "transcription_only": getattr(o,'transcription_only',False) if o else False,
        "pending": o.pending if o else None,
        "runtime": {"pid": os.getpid(), "revision": "gemini-diagnostic-3"},
        "version": "1.2", "mode": "live" if o else "demo",
        "state": o.state if o else "idle",
        "stt": {"model": CFG["stt"]["model"], "device": "CPU / int8", "ready": bool(o)},
        "gemini": {"model": o.llm.c["model"] if o else CFG["llm"]["model"],
                   "status": o.llm.connection_status if o else "unverified",
                   "error_code": getattr(o.llm,"last_error",None) if o else None,
                   "diagnostic": getattr(o.llm,"diagnostic",{}) if o else {}},
        "tts": {"engine": CFG["tts"]["engine"], "voice": CFG["tts"]["voice"]},
        "research": ({'status': o.research.report['status'], 'sources': [
            {'title':h['title'], 'url':h['href']} for h in o.research.report['sources']]}
            if o and o.research and o.research.report else None),
        "sensitivity": o.audio.sensitivity if o else CFG['audio'].get('sensitivity','normal'),
        "audio_health": ({'status': getattr(o.audio, 'stream_status', 'unknown'),
                          'frame_age_s': round(time.monotonic() - o.audio.last_frame_at, 1)
                          if getattr(o.audio, 'last_frame_at', None) is not None else None,
                          'filter_errors': getattr(o.audio, 'filter_errors', 0),
                          'capture': getattr(o.audio, 'last_capture', {})} if o else None),
        "input_device": o.audio.device if o else CFG['audio']['input_device'],
        "input_name": (o.audio.resolved_name or o.audio.device_name) if o else CFG['audio'].get('input_device_name'),
        "voice_wake": CFG['wakeword'].get('voice_name_enabled', False),
        "memory_turns": CFG.get('assistant', {}).get('history_turns', 12),
        "ram": o.metrics.sample() if o and o.metrics else None,
        "latency": list(o.metrics.recent)[-1] if o and o.metrics and o.metrics.recent else None,
    }


@app.get("/api/audit")
def audit():
    return {"enabled": AUDIT.enabled, "records": AUDIT.read(CFG.get("audit", {}).get("max_api_records", 500))}

@app.get("/api/audit/export")
def audit_export():
    import csv, io
    records = AUDIT.read(5000)
    fields = sorted({k for r in records for k in r.keys()})
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(records)
    from fastapi.responses import Response
    return Response(
        content=buf.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="viv-auditoria.csv"'},
    )


@app.post('/api/audio/transcription-test/{enabled}')
def transcription_test(enabled: str):
    if enabled not in ('on','off'):
        raise HTTPException(400, 'Valor inválido')
    o=ORCH['ref']
    if not o:raise HTTPException(409, 'Sessão de voz não iniciada')
    o.transcription_only = enabled == 'on'
    return {'ok':True,'transcription_only':o.transcription_only}


@app.post('/api/audio/sensitivity/{value}')
def sensitivity(value: str):
    if value not in ('low','normal','high'):
        raise HTTPException(400, 'Sensibilidade inválida')
    o = ORCH['ref']
    if not o:
        raise HTTPException(409, 'Sessão de voz não iniciada')
    o.audio.set_sensitivity(value)
    return {'ok': True, 'sensitivity': value}


_verify_lock = threading.Lock()
SELECTION = None

@app.get('/api/gemini/models')
def model_selection_status():
    if SELECTION is None:
        return {'status':'idle', 'selected':None, 'rows':[]}
    return SELECTION.report

@app.post('/api/gemini/models/select')
def select_model():
    if SELECTION is None:
        raise HTTPException(409, 'Sessao de voz nao iniciada')
    return {'started': SELECTION.start(), **SELECTION.report}


@app.post('/api/gemini/verify')
def verify_gemini():
    o = ORCH['ref']
    if not o:
        raise HTTPException(409, 'Sessão de voz não iniciada')
    if not _verify_lock.acquire(blocking=False):
        return {'status': 'checking'}
    try:
        return {'status': o.llm.verify_connection(generate=True), 'error_code': o.llm.last_error, 'model': o.llm.c['model'], 'diagnostic': getattr(o.llm, 'diagnostic', {})}
    finally:
        _verify_lock.release()


@app.post("/api/wake")
def wake():
    o = ORCH["ref"]
    if o:
        if getattr(o.audio, 'stream_status', None) in ('error', 'no_frames'):
            if not launch_voice(o):
                raise HTTPException(409, 'Ciclo anterior ainda encerrando; tente novamente em instantes')
        o.wake_now()
        return {"ok": True}
    return {"ok": False, "error": "assistant not running"}


@app.post("/api/confirm/{decision}")
def confirm(decision: str):
    o = ORCH["ref"]
    if o:
        o.confirm(decision == "yes")
    return {"ok": True}


@app.websocket("/ws")
async def ws(sock: WebSocket):
    await sock.accept()
    q = BUS.subscribe()
    async def send_events():
        while True:
            evt = await q.get()
            await sock.send_text(json.dumps(evt))

    async def watch_disconnect():
        while True:
            if (await sock.receive())["type"] == "websocket.disconnect":
                return

    tasks = [asyncio.create_task(send_events()), asyncio.create_task(watch_disconnect())]
    try:
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for task in tasks:
            task.cancel()
        BUS.unsubscribe(q)
        await asyncio.gather(*tasks, return_exceptions=True)



def launch_voice(orchestrator):
    """Start only when the previous owner has closed its input stream."""
    global _voice_thread
    with _voice_lock:
        if _voice_thread is not None and _voice_thread.is_alive():
            return False
        def voice_loop():
            from core.startup_diagnostics import stage, failure
            try:
                stage('Iniciando ciclo de voz')
                orchestrator.audio.stream_status = 'starting'
                orchestrator.run_forever()
            except Exception as exc:
                failure(exc)
                orchestrator.audio.stream_status = 'error'
                orchestrator.set_state('error')
                BUS.emit('sys', 'Ciclo de voz interrompido. Use ATIVAR VIV para tentar recuperar a captura.')
            finally:
                orchestrator.audio.close()
        _voice_thread = threading.Thread(target=voice_loop, daemon=True, name='viv-voice')
        _voice_thread.start()
        return True


def start(orchestrator=None):
    global SELECTION
    from core.startup_diagnostics import stage
    ORCH['ref'] = orchestrator
    if orchestrator:
        launch_voice(orchestrator)
        if not CFG.get('assistant',{}).get('local_mode',False):
            from core.model_selection import ModelSelection
            SELECTION = ModelSelection(orchestrator.llm)
            SELECTION.start()
    stage('Iniciando servidor HTTP')
    uvicorn.run(app, host=CFG['server']['host'], port=CFG['server']['port'], log_level='info')
