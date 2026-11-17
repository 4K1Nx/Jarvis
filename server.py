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


def create_app(viv, gate, audio, cfg: dict, speaker=None, settings=None, mood=None, gowa=None) -> FastAPI:
    app = FastAPI(title="Viv", docs_url=None, redoc_url=None, openapi_url=None)
    port = cfg.get("server", {}).get("port", 8765)
    allowed = {f"http://127.0.0.1:{port}", f"http://localhost:{port}"}

    def same_origin(request: Request) -> None:
        if request.headers.get("origin") not in allowed:
            raise HTTPException(403, "origem não permitida")

    @app.get("/")
    def index():
        return page("index.html")

    def page(name: str):
        # Cada arquivo da tela vai com a data de modificação no endereço: sem isso o navegador seguia usando o
        # estilo e os scripts antigos depois de uma atualização (botão sem estilo, gráfico que não aparecia).
        import re
        from fastapi.responses import HTMLResponse

        def stamp(match):
            try:
                return f'{match.group(0)}?v={int((WEB / match.group(1)).stat().st_mtime)}'
            except OSError:
                return match.group(0)
        html = re.sub(r'/static/([\w.-]+\.(?:js|css))', stamp, (WEB / name).read_text(encoding="utf-8"))
        if settings is not None and settings.get("hud.animacoes"):      # anima mesmo com o Windows em modo reduzido
            html = html.replace('<html lang="pt-BR">', '<html lang="pt-BR" data-motion="full">', 1)
        return HTMLResponse(html, headers={"Cache-Control": "no-store"})

    @app.get("/mini")
    def mini_page():
        """Só o avatar: a janelinha que fica no canto da tela enquanto a Viv está minimizada (viv/mini.py)."""
        return page("mini.html")

    @app.get("/avisos")
    def notices_page():
        """Os avisos do canto superior direito, numa janelinha própria enquanto a Viv está minimizada."""
        return page("avisos.html")

    @app.post("/api/mini/abrir")
    def mini_open(request: Request):
        same_origin(request)
        mini = getattr(app.state, "mini", None)
        return {"ok": bool(mini is not None and mini.restore())}

    @app.get("/favicon.ico")
    def favicon():
        return FileResponse(WEB / "icon-32.png", media_type="image/png")

    @app.get("/api/status")
    def status():
        tick = getattr(gate, "tick", None)
        if tick is not None:
            tick()                        # confirmação vencida não volta para a tela
        pending = gate.pending
        who = speaker.who() if speaker is not None and speaker.enrolled else None
        return {
            "mood": mood.state() if mood is not None else None,
            "speaker": {"name": who["name"], "known": who["known"], "owner": who["owner"]} if who and who["heard"] else None,
            "state": viv.state.value,
            "hibernating": bool(getattr(viv, "hibernating", False)),
            "text_only": bool(getattr(viv, "text_only", False)),
            "present": speaker.present() if speaker is not None and speaker.enrolled and hasattr(speaker, "present") else [],
            "mic": audio.input_name,
            "model": cfg.get("live", {}).get("model", ""),
            "enrolled": bool(speaker is not None and speaker.enrolled),
            "avatar": bool(settings.get("hud.avatar")) if settings is not None else True,
            "avatar_look": {"size": settings.get("avatar.tamanho"), "opacity": settings.get("avatar.opacidade")} if settings is not None else None,
            "pending": {"name": pending["name"], "text": pending.get("text") or pending["name"],
                        "voice": bool(pending.get("voice")),
                        "seconds": gate.remaining() if hasattr(gate, "remaining") else 30} if pending else None,
        }

    @app.post("/api/wake")
    def wake(request: Request):
        same_origin(request)
        viv.wake("button")
        return {"ok": True}

    local_chats: dict[str, list[dict]] = {}       # conversa com cada modelo local, enquanto a Viv estiver aberta
    local_busy: set[str] = set()

    def local_reply(model: str, text: str) -> None:
        """Responde no chat com um modelo do Ollama, mostrando o texto conforme ele chega. A Viv não participa."""
        import time
        from viv.tools import local
        history = local_chats.setdefault(model, [])
        history.append({"role": "user", "content": text})
        shown = [0.0]

        def partial(so_far):
            if time.monotonic() - shown[0] >= 0.15:
                shown[0] = time.monotonic()
                BUS.emit("chat", so_far, reply=True, model=model, final=False)
        try:
            answer = local.chat(getattr(gate, "ctx", None), model, history, partial)
            history.append({"role": "assistant", "content": answer})
            del history[:-local.CHAT_TURNS]
            BUS.emit("chat", answer, reply=True, model=model, final=True)
        except Exception as exc:
            history.pop()
            BUS.emit("chat", f"Não consegui falar com {model}: {str(exc)[:200]}", reply=True, model=model, final=True, failed=True)
        finally:
            local_busy.discard(model)

    @app.get("/api/chat/modelos")
    def chat_models():
        from viv.tools import local
        return {"modelos": [{"id": "viv", "nome": "Viv"}] +
                [{"id": m["nome"], "nome": f"{m['nome']} ({m['gb']} GB)"} for m in local.chat_models(getattr(gate, "ctx", None))]}

    @app.post("/api/chat/nova")
    async def chat_new(request: Request):
        """Recomeça do zero a conversa com um modelo local."""
        same_origin(request)
        local_chats.pop(str((await request.json()).get("modelo", "")), None)
        return {"ok": True}

    @app.post("/api/chat")
    async def chat(request: Request):
        """Mensagem digitada no chat da HUD. Para a Viv, chega como se o usuário tivesse falado; para um modelo
        local escolhido no chat, vai direto ao Ollama e a resposta volta por escrito."""
        same_origin(request)
        data = await request.json()
        raw, model = str(data.get("texto", "")), str(data.get("modelo") or "viv").strip()
        if model == "viv":
            text = " ".join(raw.split())[:2000]
            if not text:
                raise HTTPException(400, "mensagem vazia")
            viv.type(text)
            return {"ok": True}
        text = raw.strip()[:8000]
        if not text:
            raise HTTPException(400, "mensagem vazia")
        from viv.tools import local
        if model not in {m["nome"] for m in local.chat_models(getattr(gate, "ctx", None))}:
            raise HTTPException(400, "modelo não instalado")
        if model in local_busy:
            raise HTTPException(409, "esse modelo ainda está respondendo")
        local_busy.add(model)
        import threading
        threading.Thread(target=local_reply, args=(model, text), daemon=True, name="viv-chat-local").start()
        return {"ok": True}

    @app.post("/api/chat/modo")
    async def chat_mode(request: Request):
        """Só texto (ela não fala e o microfone fica fechado) ou texto e voz."""
        same_origin(request)
        viv.set_text_only(bool((await request.json()).get("so_texto")))
        return {"ok": True, "so_texto": bool(viv.text_only)}

    @app.post("/api/hibernate")
    def hibernate(request: Request):
        same_origin(request)
        viv.hibernate()
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

    @app.post("/api/answer")
    async def answer(request: Request):
        """Clique numa opção de uma pergunta da Viv (viv/tools/hud.py): ela fica sabendo da escolha."""
        same_origin(request)
        from viv.tools import hud
        data = await request.json()
        question, option = str(data.get("pergunta", "")), str(data.get("opcao", ""))
        if not hud.answer(question, option):
            raise HTTPException(400, "essa pergunta não está mais aberta")
        viv.notify(f"O usuário escolheu na tela: “{option}” para “{question}”.")
        return {"ok": True}

    def routine_rows():
        from viv.settings import days_label
        return [{**item, "dias_texto": days_label(item["dias"])} for item in settings.routine()]

    @app.get("/api/settings")
    def settings_get():
        if settings is None:
            raise HTTPException(404, "configurações indisponíveis")
        return {"items": settings.items(), "rotina": routine_rows()}

    @app.post("/api/settings")
    async def settings_set(request: Request):
        same_origin(request)
        if settings is None:
            raise HTTPException(404, "configurações indisponíveis")
        body = await request.json()
        try:
            value = await asyncio.to_thread(settings.set, str(body.get("key", "")), body.get("value"))
        except (KeyError, ValueError, RuntimeError) as exc:
            raise HTTPException(400, str(exc).strip("'\"")) from None
        return {"ok": True, "value": value}

    @app.post("/api/routine")
    async def routine_add(request: Request):
        same_origin(request)
        if settings is None:
            raise HTTPException(404, "configurações indisponíveis")
        body = await request.json()
        try:
            settings.add_routine(body.get("hora", ""), body.get("texto", ""), body.get("dias") or "todos")
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from None
        return {"ok": True, "rotina": routine_rows()}

    @app.delete("/api/routine/{item_id}")
    def routine_delete(item_id: str, request: Request):
        same_origin(request)
        if settings is None:
            raise HTTPException(404, "configurações indisponíveis")
        with settings._lock:
            before = len(settings._routine)
            settings._routine = [r for r in settings._routine if r["id"] != item_id]
            if len(settings._routine) != before:
                settings._save()
        return {"ok": True, "rotina": routine_rows()}

    @app.get("/api/screen")
    def screen():
        path = ROOT / cfg.get("tools", {}).get("vision", {}).get("screenshot_path", "data/screen.png")
        if not path.is_file():
            raise HTTPException(404, "sem captura")
        return FileResponse(path, headers={"Cache-Control": "no-store"})

    @app.post("/api/whatsapp/abrir")
    async def whatsapp_open(request: Request):
        """Clique numa conversa da lista da HUD: abre essa conversa na tela."""
        same_origin(request)
        ctx = getattr(gate, "ctx", None)
        if ctx is None:
            raise HTTPException(404, "WhatsApp indisponível")
        body = await request.json()
        contato = " ".join(str(body.get("contato") or "").split())[:120] if isinstance(body, dict) else ""
        if not contato:
            raise HTTPException(400, "informe a conversa")
        from viv.tools import registry
        result = await asyncio.to_thread(registry.call, "whatsapp_abrir", {"contato": contato}, ctx)
        if result.startswith("erro:"):
            raise HTTPException(400, result[5:].strip()[:200])
        return {"ok": True}

    @app.post("/api/whatsapp/audio")
    async def whatsapp_audio(request: Request):
        """Clique num áudio da conversa aberta na tela: tocar nas caixas de som ou transcrever."""
        same_origin(request)
        ctx = getattr(gate, "ctx", None)
        if ctx is None:
            raise HTTPException(404, "WhatsApp indisponível")
        body = await request.json()
        if not isinstance(body, dict) or body.get("acao") not in ("tocar", "transcrever"):
            raise HTTPException(400, "use tocar ou transcrever")
        from viv.tools import whatsapp
        try:
            text = await asyncio.to_thread(whatsapp.audio_action, ctx, str(body.get("jid") or ""),
                                           str(body.get("id") or ""), body["acao"])
        except ValueError as exc:
            raise HTTPException(400, str(exc)[:200]) from None
        except Exception as exc:
            raise HTTPException(409, str(exc)[:200]) from None
        return {"ok": True, "transcricao": text}

    @app.post("/api/whatsapp/evento")
    async def whatsapp_event(request: Request):
        """Mensagens novas do serviço local do WhatsApp. Sem Origin (não vem do navegador): vale só de
        127.0.0.1 e com a assinatura HMAC do segredo sorteado ao iniciar o serviço."""
        if gowa is None:
            raise HTTPException(404, "WhatsApp direto desligado")
        body = (await request.body())[:2_000_000]
        host = request.client.host if request.client else ""
        accepted = await asyncio.to_thread(gowa.webhook, body, request.headers.get("x-hub-signature-256", ""), host)
        if not accepted:
            raise HTTPException(403, "assinatura inválida")
        return {"ok": True}

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
