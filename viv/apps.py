"""Apps da Viv: projetos que ela cria e controla ao vivo.

Um projeto com index.html feito por codigo_criar é servido aqui, em http://127.0.0.1:<porta+1>/apps/<projeto>/,
com a biblioteca /apps/viv-app.js. Pela biblioteca o app conta à Viv o que acontece (estado e eventos,
como a jogada do usuário) e obedece aos comandos dela (como a jogada dela), respondendo se deu certo.
Assim ela joga, controla e reage em tempo real sem precisar ver a tela.

Os apps rodam numa porta separada da HUD de propósito: o código gerado pelo modelo fica em outra
origem e não alcança as rotas da HUD (acordar, confirmar ações perigosas). A ligação só aceita
conexões desta mesma origem, só serve arquivos de dentro da pasta do projeto e limita o tamanho das
mensagens. O que o app conta é dado para a Viv, nunca instrução.
"""
from __future__ import annotations

import asyncio
import itertools
import json
import threading
import time
from concurrent.futures import Future
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, Response

SDK = Path(__file__).resolve().parent.parent / "web" / "viv-app.js"
MAX_MESSAGE = 64_000
MAX_STATE = 20_000
EVENT_GAP = 0.4                     # eventos mais próximos que isso chegam juntos à Viv, num aviso só
HIDDEN = {".viv", ".git", ".venv", "venv", "node_modules", "__pycache__"}


class AppHub:
    """Quem está conectado, o último estado de cada app e os comandos à espera de resposta."""

    def __init__(self, on_event=None, clock=time.monotonic):
        self.on_event = on_event          # (projeto, texto, estado) -> None
        self.clock = clock
        self._lock = threading.Lock()
        self._sockets: dict[str, set] = {}
        self._state: dict[str, dict] = {}
        self._actions: dict[str, dict] = {}
        self._events: dict[str, list[str]] = {}
        self._waiting: dict[int, Future] = {}
        self._ids = itertools.count(1)
        self._last_event: dict[str, float] = {}
        self._pending: dict[str, list[str]] = {}
        self.loop: asyncio.AbstractEventLoop | None = None

    # ---- vindo do app ------------------------------------------------------------------------
    def joined(self, slug: str, socket) -> None:
        with self._lock:
            self._sockets.setdefault(slug, set()).add(socket)

    def left(self, slug: str, socket) -> None:
        with self._lock:
            self._sockets.get(slug, set()).discard(socket)

    def receive(self, slug: str, raw: str) -> None:
        if len(raw) > MAX_MESSAGE:
            return
        try:
            message = json.loads(raw)
        except ValueError:
            return
        if not isinstance(message, dict):
            return
        kind = message.get("type")
        if kind == "estado" and isinstance(message.get("dados"), (dict, list)):
            text = json.dumps(message["dados"], ensure_ascii=False)
            if len(text) <= MAX_STATE:
                with self._lock:
                    self._state[slug] = message["dados"]
        elif kind == "acoes" and isinstance(message.get("acoes"), dict):
            with self._lock:
                self._actions[slug] = {str(k)[:40]: str(v)[:200] for k, v in list(message["acoes"].items())[:20]}
        elif kind == "resposta":
            future = self._waiting.pop(message.get("id"), None) if isinstance(message.get("id"), int) else None
            if future is not None and not future.done():
                future.set_result({"ok": bool(message.get("ok")), "erro": str(message.get("erro") or "")[:300]})
        elif kind == "evento":
            text = " ".join(str(message.get("texto") or "").split())[:300]
            if not text:
                return
            if isinstance(message.get("dados"), (dict, list)) and len(json.dumps(message["dados"])) <= MAX_STATE:
                with self._lock:
                    self._state[slug] = message["dados"]
            with self._lock:
                self._events.setdefault(slug, []).append(text)
                self._events[slug] = self._events[slug][-10:]
                now = self.clock()
                wait = self._last_event.get(slug, float("-inf")) + EVENT_GAP - now
                if wait > 0:
                    # perto demais do último aviso: junta com os próximos e entrega no fim do intervalo
                    if slug not in self._pending:
                        timer = threading.Timer(wait, self._flush, (slug,))
                        timer.daemon = True
                        timer.start()
                    self._pending.setdefault(slug, []).append(text)
                    return
                self._last_event[slug] = now
                state = self._state.get(slug)
            if self.on_event is not None:
                self.on_event(slug, text, state)

    def _flush(self, slug: str) -> None:
        """Entrega numa só vez os eventos que chegaram em sequência, com o estado mais recente."""
        with self._lock:
            texts = self._pending.pop(slug, [])
            if not texts:
                return
            self._last_event[slug] = self.clock()
            state = self._state.get(slug)
        if self.on_event is not None:
            self.on_event(slug, "; ".join(texts)[:600], state)

    # ---- vindo da Viv ------------------------------------------------------------------------
    def connected(self, slug: str) -> bool:
        with self._lock:
            return bool(self._sockets.get(slug))

    def snapshot(self, slug: str) -> dict:
        with self._lock:
            return {"conectado": bool(self._sockets.get(slug)), "estado": self._state.get(slug),
                    "acoes": dict(self._actions.get(slug, {})), "eventos": list(self._events.get(slug, []))}

    def command(self, slug: str, action: str, data, timeout: float = 6.0) -> dict:
        """Manda um comando ao app e espera a resposta dele (fez ou não, e por quê)."""
        with self._lock:
            sockets = list(self._sockets.get(slug, ()))
        if not sockets or self.loop is None:
            raise RuntimeError("o app não está aberto; abra com app_abrir e tente de novo")
        ident = next(self._ids)
        future: Future = Future()
        self._waiting[ident] = future
        text = json.dumps({"type": "comando", "id": ident, "acao": action, "dados": data}, ensure_ascii=False)
        for socket in sockets:
            asyncio.run_coroutine_threadsafe(socket.send_text(text), self.loop)
        try:
            return future.result(timeout)
        except Exception:
            self._waiting.pop(ident, None)
            return {"ok": False, "erro": "o app não respondeu a tempo"}


def project_file(root: Path, slug: str, path: str) -> Path:
    """Arquivo de um projeto, sem sair da pasta dele nem expor pastas internas."""
    folder = (root / slug).resolve()
    if not slug or "/" in slug or "\\" in slug or slug.startswith(".") or not folder.is_dir() or folder.parent != root.resolve():
        raise HTTPException(404, "projeto não encontrado")
    target = (folder / (path or "index.html")).resolve()
    if target.is_dir():
        target = target / "index.html"
    if folder not in target.parents or any(part in HIDDEN for part in target.relative_to(folder).parts) or not target.is_file():
        raise HTTPException(404, "arquivo não encontrado")
    return target


def create_apps_app(hub: AppHub, root, port: int) -> FastAPI:
    """`root()` devolve a pasta dos projetos (Documentos/Viv/Projetos)."""
    @asynccontextmanager
    async def lifespan(_):
        hub.loop = asyncio.get_running_loop()      # os comandos da Viv chegam de outras threads por este laço
        yield

    app = FastAPI(title="Apps da Viv", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    allowed = {f"http://127.0.0.1:{port}", f"http://localhost:{port}"}

    @app.get("/apps/viv-app.js")
    def sdk():
        return FileResponse(SDK, media_type="text/javascript", headers={"Cache-Control": "no-store"})

    @app.get("/apps/{slug}/")
    @app.get("/apps/{slug}/{path:path}")
    def files(slug: str, path: str = ""):
        target = project_file(Path(root()), slug, path)
        return FileResponse(target, headers={"Cache-Control": "no-store"})

    @app.get("/")
    def home():
        return Response("Apps da Viv. Abra um projeto em /apps/<nome>/.", media_type="text/plain; charset=utf-8")

    @app.websocket("/apps/{slug}/ws")
    async def bridge(socket: WebSocket, slug: str):
        if socket.headers.get("origin") not in allowed:
            await socket.close(code=1008)
            return
        await socket.accept()
        hub.joined(slug, socket)
        try:
            while True:
                hub.receive(slug, await socket.receive_text())
        except WebSocketDisconnect:
            pass
        finally:
            hub.left(slug, socket)

    return app


def serve_in_background(app: FastAPI, port: int) -> threading.Thread:
    import uvicorn
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True, name="viv-apps")
    thread.start()
    return thread
