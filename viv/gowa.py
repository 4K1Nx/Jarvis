"""WhatsApp direto, sem navegador: o GoWA (go-whatsapp-web-multidevice) roda junto com a Viv.

É o mesmo serviço que o Kardap.IA usa, aqui só para a Viv e só neste computador:
- escuta apenas em 127.0.0.1, numa porta livre sorteada a cada início, com senha nova a
  cada início (nada disso fica gravado);
- os dados da sessão ficam em data/gowa/; mídias baixadas para leitura são apagadas logo
  depois de usadas, e o registro do serviço é descartado;
- as mensagens novas chegam pelo webhook /api/whatsapp/evento do servidor da Viv, assinado
  com HMAC-SHA256 por um segredo também sorteado a cada início.

Ler pela API não marca nada como lido no celular. O WhatsApp não autoriza oficialmente
clientes de terceiros em contas pessoais: o risco de bloqueio é o mesmo do WhatsApp Web
automatizado.
"""
import base64
import hashlib
import hmac
import io
import json
import os
import secrets
import re
import socket
import sqlite3
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Callable
from urllib.parse import quote, urlparse

import httpx

from viv.errors import ERRORS

DEVICE = "viv"
LOCAL_HOSTS = ("127.0.0.1", "localhost")
MAX_MEDIA = 16 * 1024 * 1024
PENDING_HOURS = 48                  # mensagem sem resposta há mais que isso não conta como pendente
SKIP_CHATS = ("status@broadcast",)


class GowaError(RuntimeError):
    pass


class Uncertain(GowaError):
    """O pedido pode ter sido executado: não dá para afirmar nem que foi, nem que não foi."""

JID = re.compile(r"[0-9A-Za-z.:_-]{3,40}@(s\.whatsapp\.net|g\.us|lid)")


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def hhmm(stamp) -> str:
    """'2026-11-13T17:02:00Z' -> '14:02' no fuso do computador."""
    try:
        return datetime.fromisoformat(str(stamp).replace("Z", "+00:00")).astimezone().strftime("%H:%M")
    except (TypeError, ValueError):
        return ""


def age_hours(stamp, now: float) -> float:
    try:
        return (now - datetime.fromisoformat(str(stamp).replace("Z", "+00:00")).timestamp()) / 3600
    except (TypeError, ValueError):
        return float("inf")


def describe(message: dict) -> str:
    """Prévia curta de uma mensagem, como a lista de conversas mostra."""
    text = " ".join(str(message.get("content") or "").split())
    kind = str(message.get("media_type") or "").lower()
    labels = {"image": "📷 Foto", "video": "🎥 Vídeo", "audio": "🎤 Áudio", "ptt": "🎤 Áudio", "document": "📄 Documento",
              "sticker": "Figurinha", "contact": "👤 Contato", "location": "📍 Localização", "call": "📞 Chamada"}
    label = labels.get(kind, "")
    return (f"{label}: {text}" if label and text else label or text)[:160]


def phone(jid: str) -> str:
    """'555181424207@s.whatsapp.net' -> '+55 51 8142-4207'."""
    digits = jid.split("@", 1)[0].split(":", 1)[0]
    if not digits.isdigit():
        return ""
    if digits.startswith("55") and len(digits) in (12, 13):
        local = digits[4:]
        return f"+55 {digits[2:4]} {local[:-4]}-{local[-4:]}"
    return "+" + digits


def jid_name(jid: str) -> str:
    return phone(jid) or jid.split("@", 1)[0]


def looks_like_number(name: str) -> bool:
    return bool(name) and sum(c.isdigit() for c in name) >= max(8, len(name) - 4)


def decode_pcm(raw: bytes, rate: int = 24000) -> bytes:
    """Áudio do WhatsApp (ogg/opus) -> PCM 16 bits mono, no formato das caixas da Viv."""
    import av
    out = bytearray()
    with av.open(io.BytesIO(raw)) as container:
        resampler = av.AudioResampler(format="s16", layout="mono", rate=rate)
        for frame in container.decode(audio=0):
            for chunk in resampler.resample(frame):
                out += chunk.to_ndarray().tobytes()
        for chunk in resampler.resample(None):
            out += chunk.to_ndarray().tobytes()
    return bytes(out)


def thumbnail(raw: bytes, size: int = 480) -> str:
    """Foto -> miniatura JPEG em data URL, pequena o bastante para a HUD."""
    from PIL import Image
    with Image.open(io.BytesIO(raw)) as image:
        image.thumbnail((size, size))
        buffer = io.BytesIO()
        image.convert("RGB").save(buffer, "JPEG", quality=80)
    return "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode()


class Gowa:
    def __init__(self, cfg: dict, viv_port: int, on_message: Callable[[str, str, str], None] | None = None,
                 client: httpx.Client | None = None, port: int | None = None, clock: Callable[[], float] = time.time):
        w = cfg.get("whatsapp", {})
        self.exe = Path(w.get("gowa_path", "bin/gowa/windows-amd64.exe"))
        self.folder = Path(w.get("data_dir", "data/gowa"))
        self.device = w.get("device", DEVICE)
        self.port = port or free_port()
        self.password = secrets.token_urlsafe(24)
        self.secret = secrets.token_urlsafe(32)
        self.viv_port, self.on_message, self.clock = viv_port, on_message, clock
        self.http = client or httpx.Client(base_url=f"http://127.0.0.1:{self.port}", auth=("viv", self.password), timeout=20)
        self.process: subprocess.Popen | None = None
        self.failed = False
        self._ready = threading.Event()
        self._avatars: dict[str, str] = {}
        self._groups: dict[str, str] = {}
        self._index: tuple[float, tuple] | None = None
        self._watching = threading.Event()

    # ---- processo -------------------------------------------------------------------
    @property
    def installed(self) -> bool:
        return self.exe.is_file()

    def command(self) -> tuple[list[str], dict]:
        """Linha de comando e ambiente. A senha e o segredo vão pelo ambiente, não pela linha de
        comando, que outros programas do computador conseguem ler."""
        args = [str(self.exe.resolve()), "rest", "--host=127.0.0.1", f"--port={self.port}", "--os=Viv",
                "--ui-enabled=false", "--ui-auto-update=false", "--mcp-enabled=false", "--auto-download-media=false",
                "--presence-pulse-enabled=false", "--presence-on-connect=unavailable",
                f"--webhook=http://127.0.0.1:{self.viv_port}/api/whatsapp/evento", "--webhook-events=message",
                "--webhook-ignore-jids=@g.us,status@broadcast"]
        env = {**os.environ, "APP_BASIC_AUTH": f"viv:{self.password}", "WHATSAPP_WEBHOOK_SECRET": self.secret}
        return args, env

    def start(self) -> bool:
        if not self.installed:
            return False
        self.folder.mkdir(parents=True, exist_ok=True)
        self._kill_orphan()
        args, env = self.command()
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        # o registro do serviço pode citar contatos: é descartado, como pedem as regras de privacidade
        self.process = subprocess.Popen(args, cwd=self.folder, env=env, stdout=subprocess.DEVNULL,
                                        stderr=subprocess.DEVNULL, creationflags=flags)
        (self.folder / "gowa.pid").write_text(str(self.process.pid), encoding="utf-8")
        threading.Thread(target=self._boot, daemon=True, name="viv-gowa").start()
        return True

    def _kill_orphan(self) -> None:
        """Um GoWA que sobrou de uma Viv que caiu trava o banco da sessão: encerra antes de abrir outro."""
        try:
            import psutil
            pid = int((self.folder / "gowa.pid").read_text(encoding="utf-8"))
            proc = psutil.Process(pid)
            if Path(proc.exe()).name.casefold() == self.exe.name.casefold():
                proc.kill()
                proc.wait(5)
        except Exception:
            pass

    def _boot(self) -> None:
        for _ in range(150):
            if self.process is not None and self.process.poll() is not None:
                return self._fail(f"o serviço do WhatsApp fechou ao iniciar (código {self.process.returncode})")
            try:
                if self.http.get("/health", timeout=2).status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            time.sleep(0.2)
        else:
            return self._fail("o serviço do WhatsApp não respondeu em 30 segundos")
        try:
            self.ensure_device()
        except GowaError as exc:
            return self._fail(str(exc))
        self._ready.set()

    def _fail(self, message: str) -> None:
        self.failed = True
        ERRORS.record("whatsapp", message)

    def ensure_device(self) -> None:
        devices = self._call("GET", "/devices", device=False) or []
        if not any(isinstance(d, dict) and d.get("id") == self.device for d in devices):
            self._call("POST", "/devices", json_body={"device_id": self.device}, device=False)

    def wait_ready(self, seconds: float = 20) -> bool:
        if self.failed:
            return False
        return self._ready.wait(seconds) and not self.failed

    def stop(self) -> None:
        self._watching.clear()
        process, self.process = self.process, None
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(5)
            except subprocess.TimeoutExpired:
                process.kill()
        try:
            (self.folder / "gowa.pid").unlink(missing_ok=True)
        except OSError:
            pass

    # ---- chamadas -----------------------------------------------------------------------
    def _call(self, method: str, path: str, *, params: dict | None = None, json_body: dict | None = None,
              timeout: float = 20, device: bool = True, uncertain: bool = False):
        headers = {"X-Device-Id": self.device} if device else {}
        try:
            response = self.http.request(method, path, params=params, json=json_body, headers=headers, timeout=timeout)
        except (httpx.ConnectError, httpx.ConnectTimeout):
            raise GowaError("sem contato com o serviço do WhatsApp") from None
        except httpx.HTTPError:
            if uncertain:                     # o pedido saiu e a resposta não voltou
                raise Uncertain("não consegui confirmar se o WhatsApp executou; não repita sem conferir") from None
            raise GowaError("o serviço do WhatsApp não respondeu a tempo") from None
        try:
            data = response.json()
        except ValueError:
            data = {}
        if response.status_code >= 400:
            message = data.get("message") if isinstance(data, dict) and isinstance(data.get("message"), str) else ""
            text = f"o WhatsApp recusou o pedido ({response.status_code})" + (f": {message[:160]}" if message else "")
            if uncertain and response.status_code >= 500:
                raise Uncertain(text + "; não repita sem conferir")
            raise GowaError(text)
        return data.get("results") if isinstance(data, dict) else None

    def _local_file(self, url: str) -> bytes:
        """Baixa um arquivo servido pelo próprio GoWA. Endereço de outro lugar é recusado."""
        parsed = urlparse(url)
        if parsed.hostname not in LOCAL_HOSTS or parsed.port != self.port:
            raise GowaError("o WhatsApp devolveu um endereço de arquivo inesperado")
        response = self.http.get(parsed.path, timeout=60)
        if response.status_code >= 400 or len(response.content) > MAX_MEDIA:
            raise GowaError("não consegui baixar o arquivo do WhatsApp")
        return response.content

    def _discard(self, relative: str) -> None:
        """Apaga a cópia local de uma mídia já lida. Só dentro de data/gowa/statics."""
        if not relative:
            return
        statics = (self.folder / "statics").resolve()
        target = (self.folder / relative).resolve()
        if statics in target.parents:
            try:
                target.unlink(missing_ok=True)
            except OSError:
                pass

    # ---- conexão --------------------------------------------------------------------------
    def status(self) -> dict:
        return self._call("GET", "/app/status") or {}

    def logged_in(self) -> bool:
        try:
            return bool(self.status().get("is_logged_in"))
        except GowaError:
            return False

    def qr(self) -> tuple[str, int]:
        """QR code de pareamento como data URL, e por quantos segundos vale."""
        result = self._call("GET", "/app/login") or {}
        link = str(result.get("qr_link") or result.get("qrLink") or "")
        seconds = int(result.get("qr_duration") or result.get("qrDuration") or 30)
        if link.startswith("data:image/png;base64,"):
            return link, seconds
        if not link:
            raise GowaError("o WhatsApp não devolveu o QR code; talvez já esteja conectado")
        return "data:image/png;base64," + base64.b64encode(self._local_file(link)).decode(), seconds

    def pair_code(self, phone: str) -> str:
        digits = "".join(c for c in str(phone) if c.isdigit())
        if len(digits) in (10, 11):
            digits = "55" + digits
        if not 12 <= len(digits) <= 15:
            raise ValueError("telefone inválido; diga o número com DDD")
        result = self._call("GET", "/app/login-with-code", params={"phone": digits}, timeout=30) or {}
        code = result.get("pair_code") or result.get("pairCode")
        if not isinstance(code, str) or not code:
            raise GowaError("o WhatsApp não devolveu o código de pareamento")
        return code

    def logout(self) -> None:
        self._call("GET", "/app/logout")

    def watch_login(self, done: Callable[[], None], refresh: Callable[[str], None] | None = None,
                    every: float = 2.0, limit: float = 180.0, qr_seconds: int = 30) -> None:
        """Acompanha o pareamento em segundo plano: renova o QR code antes de vencer e avisa quando conectar."""
        self._watching.set()

        def loop():
            started = shown = self.clock()
            while self._watching.is_set() and self.clock() - started < limit:
                time.sleep(every)
                if self.logged_in():
                    self._watching.clear()
                    return done()
                if refresh is not None and self.clock() - shown >= max(10, qr_seconds - 5):
                    try:
                        refresh(self.qr()[0])
                        shown = self.clock()
                    except GowaError:
                        pass
            self._watching.clear()
        threading.Thread(target=loop, daemon=True, name="viv-gowa-login").start()

    # ---- conversas -------------------------------------------------------------------------
    def messages(self, jid: str, limit: int) -> list[dict]:
        result = self._call("GET", f"/chat/{quote(jid, safe='@.')}/messages", params={"limit": int(limit)}) or {}
        rows = [m for m in result.get("data") or [] if isinstance(m, dict)]
        return sorted(rows, key=lambda m: str(m.get("timestamp") or ""))

    def avatar(self, jid: str) -> str:
        if jid not in self._avatars:
            try:
                result = self._call("GET", "/user/avatar", params={"phone": jid, "is_preview": "true"}, timeout=8) or {}
                url = str(result.get("url") or "")
                self._avatars[jid] = url if url.startswith("https://") else ""
            except GowaError:
                self._avatars[jid] = ""
        return self._avatars[jid]

    def local_index(self) -> tuple[set, set, dict, dict]:
        """(arquivadas, silenciadas, nomes dos contatos, LID -> telefone), lidos da base do próprio
        WhatsApp no computador, só para leitura. A API do GoWA 9.6 não informa arquivamento nem
        silêncio (o campo "archived" de /chats vem sempre falso). Se a base mudar numa versão
        futura, nada é filtrado e os nomes caem para o telefone. Atualiza a cada minuto."""
        now = self.clock()
        if self._index is not None and now - self._index[0] < 60:
            return self._index[1]
        archived, muted, names, lids = set(), set(), {}, {}
        database = (self.folder / "storages" / "whatsapp.db").resolve()
        if database.is_file():
            try:
                connection = sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True, timeout=2)
                try:
                    for jid, until, archived_flag in connection.execute(
                            "select chat_jid, muted_until, archived from whatsmeow_chat_settings"):
                        if archived_flag:
                            archived.add(str(jid))
                        if until and (int(until) < 0 or int(until) > now):
                            muted.add(str(jid))
                    lids = {str(lid).split("@")[0]: str(pn).split("@")[0]
                            for lid, pn in connection.execute("select lid, pn from whatsmeow_lid_map")}
                    for jid, first, full, push in connection.execute(
                            "select their_jid, first_name, full_name, push_name from whatsmeow_contacts"):
                        name = str(full or first or push or "").strip()
                        if name:
                            names[str(jid).split("@")[0]] = name
                finally:
                    connection.close()
            except (sqlite3.Error, ValueError, TypeError):
                pass
        value = (archived, muted, names, lids)
        self._index = (now, value)
        return value

    def canonical(self, jid: str) -> str:
        """O mesmo contato pode chegar como telefone ou como LID: devolve sempre o telefone."""
        jid = str(jid or "")
        user = jid.split("@", 1)[0].split(":", 1)[0]
        if jid.endswith("@lid"):
            _, _, _, lids = self.local_index()
            return f"{lids[user]}@s.whatsapp.net" if user in lids else jid
        return f"{user}@s.whatsapp.net" if jid.endswith("@s.whatsapp.net") else jid

    def person(self, jid: str) -> str:
        """Nome de quem tem este JID: o salvo nos contatos, senão o telefone formatado."""
        _, _, names, lids = self.local_index()
        user = jid.split("@", 1)[0].split(":", 1)[0]
        if jid.endswith("@lid"):
            user = lids.get(user, user)
        return names.get(user) or phone(user + "@s.whatsapp.net") or "Alguém"

    def author(self, message: dict) -> str:
        """Quem mandou: “Você”, ou o nome (em grupos, o de quem escreveu, não o do grupo)."""
        if message.get("is_from_me"):
            return "Você"
        name = str(message.get("sender_display_name") or "").strip()
        if name and not looks_like_number(name):
            return name
        return self.person(str(message.get("sender_jid") or "")) if message.get("sender_jid") else (name or "Alguém")

    def group_name(self, jid: str, stored: str) -> str:
        """Nome do grupo. O GoWA guarda “Group <número>” quando não sabe: pergunta ao WhatsApp uma vez."""
        if stored and not stored.startswith("Group ") and not looks_like_number(stored):
            return stored
        if jid not in self._groups:
            try:
                info = self._call("GET", "/group/info", params={"group_id": jid}, timeout=8) or {}
                name = next((str(info[key]).strip() for key in ("Name", "name", "Subject", "subject") if info.get(key)), "")
            except GowaError:
                name = ""
            self._groups[jid] = name or "Grupo sem nome"
        return self._groups[jid]

    def chat_list(self, limit: int = 15) -> list[dict]:
        """Conversas recentes no formato da lista da HUD. 'unread' conta as mensagens seguidas da
        outra pessoa no fim da conversa, quando a última chegou há menos de PENDING_HOURS."""
        archived, muted, _, _ = self.local_index()
        result = self._call("GET", "/chats", params={"limit": 60}) or {}
        chats = [c for c in result.get("data") or [] if isinstance(c, dict) and c.get("jid")
                 and c["jid"] not in SKIP_CHATS and not str(c["jid"]).endswith("@newsletter")
                 and str(c["jid"]) not in archived and not c.get("archived")]
        chats.sort(key=lambda c: str(c.get("last_message_time") or ""), reverse=True)
        rows, now = [], self.clock()
        for chat in chats[:limit]:
            jid = str(chat["jid"])
            group = jid.endswith("@g.us")
            recent = self.messages(jid, 10)
            last = recent[-1] if recent else None
            mine = bool(last and last.get("is_from_me"))
            pending = []
            silenced = jid in muted                  # conversa silenciada no celular nunca fica pendente
            if last and not silenced and age_hours(last.get("timestamp"), now) <= PENDING_HOURS:
                for message in reversed(recent):
                    if message.get("is_from_me"):
                        break
                    pending.insert(0, message)
            preview = describe(last) if last else ""
            if preview and (mine or group):          # quem mandou a última: você, ou quem do grupo
                preview = f"{self.author(last)}: {preview}"
            stored = str(chat.get("name") or "").strip()
            name = self.group_name(jid, stored) if group else (stored if stored and not looks_like_number(stored)
                                                               else self.person(jid))
            rows.append({"name": name, "jid": jid, "group": group, "muted": silenced,
                         "mine": mine, "last": preview, "unread": len(pending),
                         "novas": [{"autor": self.author(m) if group else "", "texto": describe(m),
                                    "hora": hhmm(m.get("timestamp"))} for m in pending[-3:]],
                         "photo": "" if group else self.avatar(jid)})
        return rows

    def resolve(self, contact: str) -> tuple[str, str]:
        """Nome e JID da conversa de um contato. Aceita o nome como está salvo ou um telefone."""
        from viv.tools.whatsapp import pick_chat
        wanted = " ".join(str(contact).split())
        if JID.fullmatch(wanted):                          # conversa já identificada (clique numa notificação)
            return (self.group_name(wanted, "") if wanted.endswith("@g.us") else self.person(wanted)), wanted
        digits = "".join(c for c in wanted if c.isdigit())
        if digits and len(digits) >= 10 and len(digits) >= len(wanted.replace(" ", "")) - 4:
            return wanted, (digits if len(digits) > 11 else "55" + digits) + "@s.whatsapp.net"
        found = (self._call("GET", "/chats", params={"search": wanted, "limit": 20}) or {}).get("data") or []
        names = {}
        for chat in found:
            if isinstance(chat, dict) and chat.get("jid"):
                jid = str(chat["jid"])
                stored = str(chat.get("name") or "").strip()
                names[self.group_name(jid, stored) if jid.endswith("@g.us") else stored] = jid
        if pick_chat(list(names), wanted) is None:      # o nome do grupo que a Viv mostra pode não estar na busca
            names.update({name: jid for jid, name in self._groups.items()})
        chosen = pick_chat(list(names), wanted)
        if chosen is None:
            contacts = (self._call("GET", "/user/my/contacts") or {}).get("data") or []
            names = {str(c.get("name") or "").strip(): str(c["jid"]) for c in contacts if isinstance(c, dict) and c.get("jid")}
            chosen = pick_chat(list(names), wanted)
        if chosen is None:
            similar = ", ".join([n for n in names if n][:5])
            raise GowaError(f"não achei uma conversa única para “{wanted}”" + (f". Parecidas: {similar}" if similar else ""))
        return chosen, names[chosen]

    def download(self, message_id: str, jid: str) -> bytes:
        result = self._call("GET", f"/message/{quote(str(message_id), safe='')}/download", params={"phone": jid},
                            timeout=60) or {}
        try:
            return self._local_file(str(result.get("file_url") or ""))
        finally:
            self._discard(str(result.get("file_path") or ""))

    def rows(self, jid: str, limit: int, images: int = 0) -> list[dict]:
        """Mensagens no formato que a HUD e o modelo usam, com miniatura das fotos mais recentes."""
        rows = []
        for message in self.messages(jid, limit):
            kind = str(message.get("media_type") or "").lower()
            rows.append({"id": str(message.get("id") or ""), "out": bool(message.get("is_from_me")), "meta": "",
                         "group": jid.endswith("@g.us"), "jid": jid,
                         "time": hhmm(message.get("timestamp")), "author": self.author(message),
                         "text": str(message.get("content") or ""), "audio": kind in ("audio", "ptt", "voice"),
                         "kind": kind, "image": ""})
        budget = images
        for row in reversed(rows):
            if budget <= 0:
                break
            if row["kind"] in ("image", "sticker") and row["id"]:
                try:
                    row["image"] = thumbnail(self.download(row["id"], jid))
                    budget -= 1
                except Exception:
                    pass                          # foto que não baixou fica sem miniatura
        return rows

    def send(self, jid: str, message: str) -> None:
        self._call("POST", "/send/message", json_body={"phone": jid, "message": message}, timeout=30, uncertain=True)

    # ---- mensagens novas ------------------------------------------------------------------------
    def webhook(self, body: bytes, signature: str, host: str) -> bool:
        """Evento do GoWA. Só vale vindo deste computador e com a assinatura certa."""
        if host not in ("127.0.0.1", "::1"):
            return False
        expected = "sha256=" + hmac.new(self.secret.encode(), body, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, str(signature or "")):
            return False
        try:
            event = json.loads(body)
        except ValueError:
            return True
        payload = event.get("payload") if isinstance(event, dict) else None
        if not isinstance(payload, dict) or event.get("event") != "message":
            return True
        chat = str(payload.get("chat_id") or "")
        # só conversas com uma pessoa: grupos, canais (@newsletter), status e listas de transmissão ficam de fora
        if (not chat or payload.get("is_from_me") or chat in SKIP_CHATS
                or not (chat.endswith("@s.whatsapp.net") or chat.endswith("@lid"))):
            return True
        chat = self.canonical(chat)
        name = str(payload.get("sender_display_name") or payload.get("from_name") or "").strip()
        if not name or looks_like_number(name):
            name = self.person(chat)
        text = payload.get("body") or payload.get("text") or payload.get("message") or ""
        text = text if isinstance(text, str) else ""
        kind = next((label for key, label in (("image", "foto"), ("video", "vídeo"), ("audio", "áudio"), ("ptt", "áudio"),
                                              ("document", "documento"), ("sticker", "figurinha"),
                                              ("location", "localização"), ("contact", "contato"))
                     if payload.get(key)), "texto")
        if self.on_message is not None:
            try:
                self.on_message(chat, name, kind, text[:2000])
            except Exception:
                pass
        return True
