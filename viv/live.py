"""Sessão Gemini Live e máquina de estados da Viv.

SDK google-genai 3.2 (API v1beta), nomes conferidos com scripts/probe_live.py:
- conexão: client.aio.live.connect(model=..., config=dict) como gerenciador de contexto assíncrono
- envio: session.send_realtime_input(audio=types.Blob(data, mime_type="audio/pcm;rate=16000") | text=str)
         session.send_tool_response(function_responses=[types.FunctionResponse(id, name, response)])
- recepção: session.receive() é um iterador que termina a cada turn_complete; chama-se de novo em laço
- mensagem: .data (áudio PCM 24 kHz), .tool_call.function_calls[i].{id,name,args}, .go_away,
            .session_resumption_update.{new_handle,resumable},
            .server_content.{interrupted,turn_complete,input_transcription,output_transcription}
"""
import asyncio
import threading
import time
from datetime import datetime
from enum import Enum
from typing import Callable

from google.genai import types

from viv.bus import BUS
from viv.persona import system_instruction
from viv.tools import registry

MAX_FAILURES = 5
SILENCE = bytes(640)
SLEEP_TOOL = {"name": "viv_dormir",
              "description": "O usuário se despediu ou pediu para você dormir ou parar de ouvir.",
              "parameters": {"type": "object", "properties": {}, "required": []}}
MESSAGES = {
    "auth": ("Chave do Gemini ausente ou inválida", "Confira o arquivo .env."),
    "quota": ("Cota do Gemini atingida", "Tente mais tarde."),
    "other": ("Sem conexão com o Gemini", "Não consegui conectar depois de várias tentativas. Confira a internet."),
}


class State(str, Enum):
    SLEEPING = "sleeping"
    LISTENING = "listening"
    THINKING = "thinking"
    SPEAKING = "speaking"
    EXECUTING = "executing"
    ERROR = "error"


class MissingKey(Exception):
    pass


class _Reconnect(Exception):
    """O servidor pediu para reconectar (go_away) ou a conexão caiu sem erro."""


def classify(exc: BaseException) -> str:
    if isinstance(exc, MissingKey):
        return "auth"
    text = f"{getattr(exc, 'code', '')} {exc}".lower()
    if any(k in text for k in ("api key", "api_key", "permission_denied", "unauthenticated", "401", "403")):
        return "auth"
    if any(k in text for k in ("resource_exhausted", "quota", "429")):
        return "quota"
    return "other"


def build_config(cfg: dict, memory, handle: str | None = None) -> dict:
    live = cfg.get("live", {})
    return {
        "response_modalities": ["AUDIO"],
        "speech_config": {
            "voice_config": {"prebuilt_voice_config": {"voice_name": live.get("voice", "Aoede")}},
            "language_code": live.get("language", "pt-BR")},
        "input_audio_transcription": {},
        "output_audio_transcription": {},
        "session_resumption": {"handle": handle},
        "system_instruction": system_instruction(cfg, memory, datetime.now()),
        "tools": [{"function_declarations": registry.declarations() + [SLEEP_TOOL]}],
    }


class Viv:
    def __init__(self, cfg: dict, audio, gate, memory, watcher, connect: Callable, gaps=None,
                 clock: Callable[[], float] = time.monotonic, nap: Callable = asyncio.sleep):
        self.cfg, self.audio, self.gate, self.memory, self.watcher = cfg, audio, gate, memory, watcher
        self.connect, self.gaps, self.clock, self.nap = connect, gaps, clock, nap
        self.idle_seconds = float(cfg.get("assistant", {}).get("idle_seconds", 60))
        self.state = State.SLEEPING
        self._loop: asyncio.AbstractEventLoop | None = None
        self._lock = threading.Lock()
        self._wake_requested = False
        self._sleep_requested = False
        self._outbox: list[str] = []
        registry.load_all()

    # ---- API thread-safe -------------------------------------------------
    def wake(self, reason: str = "") -> None:
        with self._lock:
            self._wake_requested = True

    def sleep(self) -> None:
        with self._lock:
            self._sleep_requested = True

    def notify(self, text: str) -> None:
        """Entrega um aviso do programa ao modelo (confirmação resolvida, lembrete)."""
        with self._lock:
            self._outbox.append(text)
            self._wake_requested = True

    # ---- laço principal --------------------------------------------------
    async def run(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._set(State.SLEEPING, force=True)
        while True:
            await self._wait_for_wake()
            await self._awake()
            self.audio.flush()
            self.watcher.reset()
            self._set(State.SLEEPING)

    async def _wait_for_wake(self) -> None:
        while True:
            with self._lock:
                if self._wake_requested:
                    # pedidos de sono feitos enquanto dormia não valem para a sessão que começa
                    self._wake_requested = self._sleep_requested = False
                    return
            await asyncio.to_thread(self.watcher.run_once)

    async def _awake(self) -> None:
        failures, handle, first = 0, None, True
        while True:
            started = self.clock()
            try:
                async with self.connect(build_config(self.cfg, self.memory, handle)) as session:
                    if first:
                        self.audio.beep("wake")
                        first = False
                    self._set(State.LISTENING, force=True)
                    self._handle_box = [handle]
                    try:
                        await self._converse(session)
                    finally:
                        handle = self._handle_box[0]
                self.audio.beep("sleep")
                return
            except _Reconnect:
                if self.clock() - started >= 10:
                    failures = 0
                continue
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                kind = classify(exc)
                if self.clock() - started >= 10:
                    failures = 0
                failures += 1
                if kind == "other" and failures < MAX_FAILURES:
                    BUS.emit("state", state=self.state.value, reconnecting=True)
                    await self.nap(min(2 ** (failures - 1), 30))
                    continue
                await self._fail(kind)
                return

    async def _fail(self, kind: str) -> None:
        title, body = MESSAGES[kind]
        self._set(State.ERROR)
        BUS.emit("card", title, kind="data", body=body, ok=False)
        print(f"Viv: {title}. {body}")
        if kind == "quota":
            self.audio.beep("error")
        if self.gaps is not None:
            self.gaps.record("gemini_quota" if kind == "quota" else "conversation_error")
        with self._lock:
            self._outbox.clear()
            self._wake_requested = False
        await self.nap(3)

    # ---- uma sessão conectada ---------------------------------------------
    async def _converse(self, session) -> None:
        self._activity = self.clock()
        self._user_text, self._viv_text = "", ""
        self._turn_done, self._sleep_after_turn = False, False
        tasks = [asyncio.create_task(c) for c in (self._send_mic(session), self._receive(session),
                                                  self._watchdog(session))]
        try:
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                task.result()          # propaga exceção ou termina normalmente (pedido de sono)
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _send_mic(self, session) -> None:
        while True:
            frame = await asyncio.to_thread(self.audio.read, 0.05)
            if frame is None:
                continue
            # quadro barrado pelo portão de eco vira silêncio, para o fluxo seguir contínuo
            data = frame if self.audio.should_send(frame) else SILENCE
            await session.send_realtime_input(audio=types.Blob(data=data, mime_type="audio/pcm;rate=16000"))

    async def _receive(self, session) -> None:
        while True:
            got = False
            async for message in session.receive():
                got = True
                await self._on_message(session, message)
            if not got:
                raise _Reconnect()     # iterador vazio: conexão encerrada pelo servidor

    async def _watchdog(self, session) -> None:
        """Decide quando voltar a ouvir e quando dormir. Retornar encerra a sessão."""
        while True:
            await asyncio.sleep(0.05)
            self.gate.tick()
            with self._lock:
                outbox, self._outbox = self._outbox, []
                sleep_now = self._sleep_requested
                self._wake_requested = False
            for text in outbox:
                self._activity = self.clock()
                await session.send_realtime_input(text=f"[Aviso do sistema] {text}")
            if sleep_now:
                return
            playing = self.audio.is_playing()
            if playing or self.gate.pending is not None or self.state == State.EXECUTING:
                self._activity = self.clock()
            if self._turn_done and not playing:
                self._turn_done = False
                if self._sleep_after_turn:
                    return
                self._set(State.LISTENING)
            if self.clock() - self._activity >= self.idle_seconds:
                return

    async def _on_message(self, session, message) -> None:
        update = getattr(message, "session_resumption_update", None)
        if update is not None and update.new_handle and update.resumable:
            self._handle_box[0] = update.new_handle
        if getattr(message, "go_away", None) is not None:
            raise _Reconnect()

        if message.data:
            await self._finish_user_turn()
            self._activity = self.clock()
            self._turn_done = False
            self.audio.play(message.data)
            self._set(State.SPEAKING)

        if message.tool_call is not None:
            await self._finish_user_turn()
            await self._run_tools(session, message.tool_call.function_calls)

        content = message.server_content
        if content is None:
            return
        if content.interrupted:
            self.audio.flush()
            self._turn_done = False
            self._save_viv_turn()
            self._set(State.LISTENING)
        heard = content.input_transcription
        if heard is not None and heard.text:
            self._activity = self.clock()
            self._user_text += heard.text
            BUS.emit("transcript", self._user_text.strip(), role="user", final=False)
            if heard.finished:
                await self._finish_user_turn()
        said = content.output_transcription
        if said is not None and said.text:
            self._viv_text += said.text
            BUS.emit("transcript", self._viv_text.strip(), role="viv", final=False)
        if content.turn_complete:
            await self._finish_user_turn()
            self._save_viv_turn()
            self._turn_done = True

    async def _finish_user_turn(self) -> None:
        text, self._user_text = self._user_text.strip(), ""
        if not text:
            return
        BUS.emit("transcript", text, role="user", final=True)
        self.memory.add_turn("user", text)
        self._set(State.THINKING)
        # a verificação de voz é lenta; roda fora do laço de eventos
        await asyncio.to_thread(self.gate.on_user_utterance, text, self.audio.recent())

    def _save_viv_turn(self) -> None:
        text, self._viv_text = self._viv_text.strip(), ""
        if text:
            BUS.emit("transcript", text, role="viv", final=True)
            self.memory.add_turn("viv", text)

    async def _run_tools(self, session, calls) -> None:
        self._activity = self.clock()
        self._set(State.EXECUTING)
        responses = []
        for call in calls:
            if call.name == SLEEP_TOOL["name"]:
                self._sleep_after_turn = True
                result = "ok; despeça-se em poucas palavras"
            else:
                result = await asyncio.to_thread(self.gate.submit, call.name, dict(call.args or {}))
            responses.append(types.FunctionResponse(id=call.id, name=call.name, response={"result": result}))
        self._activity = self.clock()
        await session.send_tool_response(function_responses=responses)
        self._set(State.THINKING)

    def _set(self, state: State, force: bool = False) -> None:
        if force or state != self.state:
            self.state = state
            BUS.emit("state", state=state.value)
