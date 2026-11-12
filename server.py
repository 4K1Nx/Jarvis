"""Servidor local da HUD: arquivos estáticos, estado, ativação, confirmação e eventos por WebSocket.

Escuta só em 127.0.0.1. Toda ação (POST e WebSocket) exige o cabeçalho Origin da própria
HUD, para que outra página aberta no navegador não possa acordar a Viv nem confirmar ações.
"""
import asyncio
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from viv.bus import BUS

ROOT = Path(__file__).resolve().parent
WEB = ROOT / "web"


def create_app(viv, gate, audio, cfg: dict, speaker=None) -> FastAPI:
    app = FastAPI(title="Viv", docs_url=None, redoc_url=None, openapi_url=None)
    port = cfg.get("server", {}).get("port", 8765)
    allowed = {f"http://127.0.0.1:{port}", f"http://localhost:{port}"}

    def same_origin(request: Request) -> None:
        if request.headers.get("origin") not in allowed:
            raise HTTPException(403, "origem não permitida")

    @app.get("/")
    def index():
        return FileResponse(WEB / "index.html", headers={"Cache-Control": "no-store"})

    @app.get("/api/status")
    def status():
        pending = gate.pending
        return {
            "state": viv.state.value,
            "mic": audio.input_name,
            "model": cfg.get("live", {}).get("model", ""),
            "enrolled": bool(speaker is not None and speaker.enrolled),
            "pending": {"name": pending["name"], "args": pending["args"]} if pending else None,
        }

    @app.post("/api/wake")
    def wake(request: Request):
        same_origin(request)
        viv.wake("button")
        return {"ok": True}

    @app.post("/api/sleep")
    def sleep(request: Request):
        same_origin(request)
        viv.sleep()
        return {"ok": True}

    @app.post("/api/confirm/{decision}")
    async def confirm(decision: str, request: Request):
        same_origin(request)
        if decision not in ("sim", "nao"):
            raise HTTPException(400, "use sim ou nao")
        await asyncio.to_thread(gate.on_click, decision == "sim")   # a ferramenta pode demorar
        return {"ok": True}

    @app.get("/api/screen")
    def screen():
        path = ROOT / cfg.get("tools", {}).get("vision", {}).get("screenshot_path", "data/screen.png")
        if not path.is_file():
            raise HTTPException(404, "sem captura")
        return FileResponse(path, headers={"Cache-Control": "no-store"})

    @app.websocket("/ws")
    async def ws(socket: WebSocket):
        if socket.headers.get("origin") not in allowed:
            await socket.close(code=1008)
            return
        await socket.accept()
        queue = BUS.subscribe()

        async def pump():
            while True:
                await socket.send_json(await queue.get())

        async def watch():
            try:
                while True:
                    await socket.receive_text()
            except WebSocketDisconnect:
                pass

        tasks = [asyncio.create_task(pump()), asyncio.create_task(watch())]
        try:
            await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        finally:
            BUS.unsubscribe(queue)
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    app.mount("/static", StaticFiles(directory=WEB), name="static")
    return app


def serve(app: FastAPI, cfg: dict) -> None:
    import uvicorn
    s = cfg.get("server", {})
    uvicorn.run(app, host=s.get("host", "127.0.0.1"), port=s.get("port", 8765), log_level="warning")
