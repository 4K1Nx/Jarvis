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
from collections import deque
from datetime import datetime
from enum import Enum
from typing import Callable

import numpy as np

from google.genai import types

from viv.bus import BUS
from viv.errors import ERRORS
from viv.persona import system_instruction
from viv.tools import registry

MAX_FAILURES = 5
SAFE_VOICE = "Aoede"                # aceita por todos os modelos Live
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


def build_config(cfg: dict, memory, handle: str | None = None, extra: str = "") -> dict:
    live = cfg.get("live", {})
    return {
        "response_modalities": ["AUDIO"],
        "speech_config": {
            "voice_config": {"prebuilt_voice_config": {"voice_name": live.get("voice", SAFE_VOICE)}},
            "language_code": live.get("language", "pt-BR")},
        "input_audio_transcription": {},
        "output_audio_transcription": {},
        "session_resumption": {"handle": handle},
        "system_instruction": system_instruction(cfg, memory, datetime.now(), extra),
        "tools": [{"function_declarations": registry.declarations() + [SLEEP_TOOL]}],
    }


class Viv:
    def __init__(self, cfg: dict, audio, gate, memory, watcher, connect: Callable, gaps=None,
                 clock: Callable[[], float] = time.monotonic, nap: Callable = asyncio.sleep,
                 speaker=None, mood=None, people=None):
        self.cfg, self.audio, self.gate, self.memory, self.watcher = cfg, audio, gate, memory, watcher
        self.speaker, self.mood, self.people = speaker, mood, people
        self._heard = b""                 # áudio da chamada pelo nome, reenviado ao abrir a conversa
        self._told: tuple = ("", "")      # quem fala e o humor que o modelo já conhece
        self.connect, self.gaps, self.clock, self.nap = connect, gaps, clock, nap
        self.idle_seconds = float(cfg.get("assistant", {}).get("idle_seconds", 60))
        self.state = State.SLEEPING
        self._loop: asyncio.AbstractEventLoop | None = None
        self._lock = threading.Lock()
        self._wake_requested = False
        self._sleep_requested = False
        self._outbox: list[str] = []
        self._passing: list[str] = []         # avisos que só valem com ela acordada (mention)
        self._captions: deque = deque()       # (posição do áudio, texto, final) à espera de tocar
        self._caption_mark = 0
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

    def mention(self, text: str) -> bool:
        """Aviso de passagem (uma mensagem nova chegou): ela fala só se estiver acordada. Dormindo,
        nada acontece e o aviso não fica guardado para depois."""
        with self._lock:
            if self.state in (State.SLEEPING, State.ERROR):
                return False
            self._passing.append(text)
            return True

    def remind(self, text: str) -> None:
        self.notify(f"Lembrete agendado pelo usuário chegou na hora: {text}")

    # ---- laço principal --------------------------------------------------
    async def run(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._set(State.SLEEPING, force=True)
        while True:
            await self._wait_for_wake()
            await self._awake()
            with self._lock:
                self._passing.clear()
            self.audio.flush()
            self.watcher.reset()
            self._set(State.SLEEPING)

    async def _wait_for_wake(self) -> None:
        while True:
            self.gate.tick()              # uma confirmação pendente também vence com a Viv dormindo
            with self._lock:
                if self._wake_requested:
                    # pedidos de sono feitos enquanto dormia não valem para a sessão que começa
                    self._wake_requested = self._sleep_requested = False
                    return
            await asyncio.to_thread(self.watcher.run_once)

    def _context(self) -> str:
        """Trechos da instrução de sistema que dependem do momento: humor, vozes e pessoas."""
        parts = [self.mood.prompt() if self.mood is not None else ""]
        if self.speaker is not None and self.speaker.enrolled:
            who, others = self.speaker.who(), ", ".join(self.speaker.people)
            called = f" Quem chamou você agora: {who['name']}." if who["known"] else ""
            # O modelo nunca decide quem pode ver o quê: isso é do portão (viv/safety.py). Dizer a ele
            # "voz não reconhecida" o fazia recusar pedidos do próprio dono sem chamar a ferramenta.
            parts.append(f"Reconhecimento de voz: o dono é {self.speaker.owner or 'o usuário'}."
                         + (f" Outras vozes cadastradas: {others}." if others else "") + called
                         + " Use o nome de quem fala quando souber. Quem controla o acesso a mensagens, e-mails e "
                         "arquivos é o sistema, não você: nunca recuse um pedido por causa da voz nem diga que não "
                         "reconhece a voz de alguém; chame a ferramenta pedida. Se o sistema precisar de confirmação, a "
                         "ferramenta devolve \"pendente\" e você segue a regra da confirmação. Só fale de reconhecimento "
                         "de voz se perguntarem, e nesse caso consulte voz_quem_fala.")
        if self.people is not None:
            parts.append(self.people.prompt_block())
        return "\n\n".join(p for p in parts if p)

    def _now(self) -> tuple:
        who = self.speaker.who() if self.speaker is not None and self.speaker.enrolled else {"heard": False}
        voice = who["name"] if who["heard"] and who["known"] else ""
        return voice, (self.mood.name if self.mood is not None and self.mood.enabled else "")

    def _note(self) -> str:
        """Aviso curto, anexado ao resultado de uma ferramenta, quando quem fala ou o humor mudou
        no meio da conversa. Não gera fala: o modelo só passa a saber."""
        voice, mood = now = self._now()
        changed = [f"quem fala agora: {voice}" if voice and voice != self._told[0] else "",
                   f"seu humor agora: {mood}" if mood and mood != self._told[1] else ""]
        self._told = now
        changed = "; ".join(c for c in changed if c)
        return f" [contexto: {changed}]" if changed else ""

    async def _awake(self) -> None:
        failures, handle = 0, None
        self.audio.beep("wake")               # resposta imediata: a conexão leva um ou dois segundos
        self._set(State.THINKING, force=True)
        self._heard = getattr(self.watcher, "take_heard", lambda: b"")()
        if self.mood is not None:
            self.mood.feel("madrugada" if datetime.now().hour < 5 else "acordou")
        if self.speaker is not None and self._heard:
            heard = np.frombuffer(self._heard, dtype=np.int16).astype(np.float32) / 32768.0
            await asyncio.to_thread(self.speaker.hear, heard)
        while True:
            started = self.clock()
            try:
                self._told = self._now()
                async with self.connect(build_config(self.cfg, self.memory, handle, self._context())) as session:
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
                live = self.cfg.setdefault("live", {})
                if "voice" in str(exc).lower() and live.get("voice", SAFE_VOICE) != SAFE_VOICE:
                    # a voz escolhida não existe neste modelo: volta para a padrão em vez de ficar muda
                    BUS.emit("card", f"Voz {live['voice']} indisponível", kind="data", ok=False,
                             body=f"Este modelo não aceita essa voz. Voltei para {SAFE_VOICE}; troque em Configurações.")
                    ERRORS.record("voz", f"{live['voice']}: {exc}")
                    live["voice"] = SAFE_VOICE
                    continue
                if "already connected" in str(exc).lower():
                    # retomar pela alça antiga colide com a conexão que ainda não fechou: começa uma sessão nova
                    handle = None
                kind = classify(exc)
                ERRORS.record("conexão Gemini", f"{type(exc).__name__}: {exc}")
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
        heard, self._heard = self._heard, b""
        for start in range(0, len(heard), 3200):     # "Ei, Viv, que horas são?": ela já ouve o pedido
            await session.send_realtime_input(audio=types.Blob(data=heard[start:start + 3200],
                                                               mime_type="audio/pcm;rate=16000"))
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
            self._pump_captions(everything=True)

    # ---- legenda da Viv no ritmo do áudio ------------------------------------------------
    # O Gemini manda o texto da fala bem antes de o áudio terminar de tocar. Mostrar na hora fazia a
    # tela (e o destaque do WhatsApp) correr à frente da voz: ela falava da mãe e a tela já estava na
    # namorada. Cada trecho de texto passa a aparecer quando o áudio que veio antes dele começa a tocar.
    def _caption(self, text: str, final: bool) -> None:
        position = getattr(self.audio, "position", None)
        if position is None:
            BUS.emit("transcript", text, role="viv", final=final)
            return
        queued, played = position()
        mark, self._caption_mark = (queued if final else self._caption_mark), queued
        if played >= mark and not self._captions:
            BUS.emit("transcript", text, role="viv", final=final)
        else:
            self._captions.append((mark, text, final))

    def _pump_captions(self, everything: bool = False) -> None:
        position = getattr(self.audio, "position", None)
        if not self._captions:
            return
        # sem nada tocando (fala interrompida ou caixa parada), não há o que esperar
        if position is None or everything or not self.audio.is_playing():
            played = float("inf")
        else:
            played = position()[1]
        while self._captions and self._captions[0][0] <= played:
            _, text, final = self._captions.popleft()
            BUS.emit("transcript", text, role="viv", final=final)

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
            self._pump_captions()
            with self._lock:
                outbox, self._outbox = self._outbox + self._passing, []
                self._passing = []
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
            self._pump_captions(everything=True)
            position = getattr(self.audio, "position", None)
            self._caption_mark = position()[0] if position is not None else 0
            self._turn_done = False
            self._save_viv_turn()
            if self.mood is not None:
                self.mood.feel("interrompida")
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
            self._caption(self._viv_text.strip(), final=False)
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
        if self.mood is not None:
            self.mood.hear(text)
        # o reconhecimento de voz é lento; roda fora do laço de eventos
        await asyncio.to_thread(self._hear, text, self.audio.take_speech())

    def _hear(self, text: str, speech) -> None:
        if self.speaker is not None:
            self.speaker.hear(speech)
        self.gate.on_user_utterance(text, speech)

    def _save_viv_turn(self) -> None:
        text, self._viv_text = self._viv_text.strip(), ""
        if text:
            self._caption(text, final=True)
            self.memory.add_turn("viv", text)

    async def _run_tools(self, session, calls) -> None:
        self._activity = self.clock()
        # a fala que pediu a ferramenta pode ainda não ter fechado: a voz e o pedido entram antes
        await self._finish_user_turn()
        self._set(State.EXECUTING)
        responses = []
        for call in calls:
            if call.name == SLEEP_TOOL["name"]:
                self._sleep_after_turn = True
                result = "ok; despeça-se em poucas palavras"
            else:
                result = await asyncio.to_thread(self.gate.submit, call.name, dict(call.args or {}))
                if self.mood is not None:
                    self.mood.feel("erro" if result.startswith("erro:") else "trabalho")
            if not responses:
                result += self._note()
            responses.append(types.FunctionResponse(id=call.id, name=call.name, response={"result": result}))
        self._activity = self.clock()
        await session.send_tool_response(function_responses=responses)
        self._set(State.THINKING)

    def _set(self, state: State, force: bool = False) -> None:
        if force or state != self.state:
            self.state = state
            BUS.emit("state", state=state.value)
