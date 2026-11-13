"""WhatsApp direto (GoWA) com um servidor falso no lugar do serviço: mesmas rotas e formatos da API v9.6."""
import base64
import hashlib
import hmac
import io
import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from viv import gowa as direct
from viv.drafts import DRAFTS
from viv.gowa import Gowa, GowaError, Uncertain
from viv.people import People
from viv.settings import Settings
from viv.tools import registry, whatsapp
from viv.tools.registry import Context

NOW = datetime(2026, 11, 13, 18, 0, tzinfo=timezone.utc)
BIA, CHEFE, GRUPO = "5527999990001@s.whatsapp.net", "5527999990002@s.whatsapp.net", "120363000000000001@g.us"


def stamp(minutes_ago):
    return (NOW - timedelta(minutes=minutes_ago)).isoformat().replace("+00:00", "Z")


def png():
    from PIL import Image
    buffer = io.BytesIO()
    Image.new("RGB", (900, 600), (200, 80, 120)).save(buffer, "PNG")
    return buffer.getvalue()


class FakeGowa:
    """Servidor falso: guarda o que foi pedido e responde como o GoWA."""

    def __init__(self, port):
        self.port, self.calls, self.sent, self.fail_send, self.logged = port, [], [], None, True
        self.chats = [{"jid": CHEFE, "name": "Carlos Souza", "last_message_time": stamp(300)},
                      {"jid": BIA, "name": "Ana Beatriz Lima", "last_message_time": stamp(5)},
                      {"jid": GRUPO, "name": "Família", "last_message_time": stamp(60)},
                      {"jid": "status@broadcast", "name": "", "last_message_time": stamp(1)}]
        self.messages = {
            BIA: [{"id": "B3", "content": "", "is_from_me": False, "media_type": "audio", "timestamp": stamp(5),
                   "sender_display_name": "Ana Beatriz Lima"},
                  {"id": "B1", "content": "oi amor, vem hoje?", "is_from_me": False, "timestamp": stamp(20),
                   "sender_display_name": "Ana Beatriz Lima"},
                  {"id": "B0", "content": "chego às 8", "is_from_me": True, "timestamp": stamp(60)},
                  {"id": "B2", "content": "olha", "is_from_me": False, "media_type": "image", "timestamp": stamp(10),
                   "sender_display_name": "Ana Beatriz Lima"}],
            CHEFE: [{"id": "C1", "content": "Reunião amanhã", "is_from_me": False, "timestamp": stamp(300)},
                    {"id": "C2", "content": "ok, estarei lá", "is_from_me": True, "timestamp": stamp(290)}],
            GRUPO: [{"id": "G1", "content": "foto da festa", "is_from_me": False, "timestamp": stamp(60)}],
        }
        self.files = {"B2": ("statics/media/bia/foto.png", png()), "B3": ("statics/media/bia/audio.ogg", b"OggS-fake")}

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path, query = request.url.path, dict(request.url.params)
        self.calls.append((request.method, path, query, request.headers.get("x-device-id")))
        ok = lambda results: httpx.Response(200, json={"code": "SUCCESS", "results": results})
        if path == "/app/status":
            return ok({"device_id": "viv", "is_connected": True, "is_logged_in": self.logged})
        if path == "/chats":
            found = [c for c in self.chats if query.get("search", "").casefold() in c["name"].casefold()]
            return ok({"data": found})
        if path.startswith("/chat/") and path.endswith("/messages"):
            jid = path[len("/chat/"):-len("/messages")]
            rows = sorted(self.messages.get(jid, []), key=lambda m: m["timestamp"], reverse=True)
            return ok({"data": rows[:int(query.get("limit", 50))]})
        if path == "/user/avatar":
            return ok({"url": "https://pps.whatsapp.net/v/" + query["phone"].split("@")[0] + ".jpg"})
        if path == "/user/my/contacts":
            return ok({"data": [{"jid": "5527999990003@s.whatsapp.net", "name": "Dona Marta"}]})
        if path.startswith("/message/") and path.endswith("/download"):
            relative, _ = self.files[path.split("/")[2]]
            return ok({"file_path": relative, "file_url": f"http://localhost:{self.port}/{relative}"})
        if path.startswith("/statics/"):
            return httpx.Response(200, content=next(raw for rel, raw in self.files.values() if "/" + rel == path))
        if path == "/send/message":
            body = json.loads(request.content)
            if self.fail_send == "timeout":
                self.sent.append(body)                       # chegou, mas a resposta se perdeu
                raise httpx.ReadTimeout("sem resposta", request=request)
            if self.fail_send == "recusado":
                return httpx.Response(400, json={"code": "INVALID", "message": "phone inválido"})
            self.sent.append(body)
            return ok({"message_id": "X1", "status": "sent"})
        return httpx.Response(404, json={"message": "rota desconhecida"})


@pytest.fixture
def server(tmp_path):
    fake = FakeGowa(39001)
    client = httpx.Client(base_url="http://127.0.0.1:39001", transport=httpx.MockTransport(fake))
    service = Gowa({"whatsapp": {"data_dir": str(tmp_path / "gowa"), "gowa_path": str(tmp_path / "gowa.exe")}}, 8765,
                   client=client, port=39001, clock=lambda: NOW.timestamp())
    (tmp_path / "gowa.exe").write_bytes(b"")
    for relative, _ in fake.files.values():
        target = tmp_path / "gowa" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"copia local")
    service._ready.set()
    return fake, service, tmp_path


def test_command_listens_only_locally_and_keeps_secrets_off_the_command_line(server):
    _, service, _ = server
    args, env = service.command()
    line = " ".join(args)
    assert "--host=127.0.0.1" in line and "--ui-enabled=false" in line and "--mcp-enabled=false" in line
    assert "--auto-download-media=false" in line and "--presence-pulse-enabled=false" in line
    assert "/api/whatsapp/evento" in line and "--webhook-ignore-jids=@g.us,status@broadcast" in line
    assert service.password not in line and service.secret not in line
    assert env["APP_BASIC_AUTH"] == f"viv:{service.password}" and env["WHATSAPP_WEBHOOK_SECRET"] == service.secret
    assert Gowa({}, 8765).password != service.password, "senha nova a cada início"


def test_chat_list_shows_pending_replies_previews_and_photos(server):
    fake, service, _ = server
    chats = service.chat_list()
    assert [c["name"] for c in chats] == ["Ana Beatriz Lima", "Família", "Carlos Souza"], "status fica de fora"
    bia, grupo, chefe = chats
    assert bia["unread"] == 3 and bia["last"] == "🎤 Áudio" and bia["photo"].startswith("https://pps.whatsapp.net/")
    assert chefe["unread"] == 0, "a última é minha: nada pendente"
    assert grupo["photo"] == "" and grupo["unread"] == 1
    assert all(device == "viv" for _, path, _, device in fake.calls if path != "/devices")
    assert whatsapp.clean_chats(chats)[0] == {"name": "Ana Beatriz Lima", "last": "🎤 Áudio", "unread": 3,
                                              "photo": "https://pps.whatsapp.net/v/5527999990001.jpg"}


def test_old_unanswered_message_is_not_pending(server):
    fake, service, _ = server
    fake.messages[CHEFE] = [{"id": "C9", "content": "?", "is_from_me": False, "timestamp": stamp(60 * 72)}]
    assert next(c for c in service.chat_list() if c["name"] == "Carlos Souza")["unread"] == 0


def test_rows_are_in_order_with_local_time_audio_and_a_thumbnail_and_media_is_deleted(server):
    fake, service, tmp_path = server
    rows = service.rows(BIA, 10, images=2)
    assert [r["id"] for r in rows] == ["B0", "B1", "B2", "B3"]
    assert rows[0]["out"] and rows[0]["time"] == datetime.fromisoformat(stamp(60).replace("Z", "+00:00")).astimezone().strftime("%H:%M")
    assert rows[3]["audio"] and not rows[3]["image"], "áudio não vira miniatura"
    assert rows[2]["image"].startswith("data:image/jpeg;base64,")
    from PIL import Image
    with Image.open(io.BytesIO(base64.b64decode(rows[2]["image"].split(",", 1)[1]))) as image:
        assert max(image.size) <= 480
    assert not (tmp_path / "gowa/statics/media/bia/foto.png").exists(), "a cópia baixada é apagada depois de usada"
    clean = whatsapp.clean_messages(rows)
    assert clean[1]["autor"] == "Ana Beatriz Lima" and clean[0]["autor"] == "Você" and whatsapp.IMAGE.match(clean[2]["imagem"])


def test_media_from_an_unexpected_address_is_refused(server):
    fake, service, _ = server
    fake.files["B2"] = ("statics/x.png", b"")
    original = fake.__call__

    def evil(request):
        if request.url.path.endswith("/download"):
            return httpx.Response(200, json={"results": {"file_url": "http://169.254.169.254/latest", "file_path": ""}})
        return original(request)
    service.http = httpx.Client(base_url="http://127.0.0.1:39001", transport=httpx.MockTransport(evil))
    with pytest.raises(GowaError, match="inesperado"):
        service.download("B2", BIA)


def test_resolve_by_saved_name_contact_list_or_phone(server):
    _, service, _ = server
    assert service.resolve("ana beatriz") == ("Ana Beatriz Lima", BIA)
    assert service.resolve("Dona Marta") == ("Dona Marta", "5527999990003@s.whatsapp.net")
    assert service.resolve("27 99999-0009") == ("27 99999-0009", "5527999990009@s.whatsapp.net")
    with pytest.raises(GowaError, match="não achei"):
        service.resolve("Fulano")


def test_send_success_refusal_and_uncertain_result(server):
    fake, service, _ = server
    service.send(BIA, "chego às 8")
    assert fake.sent == [{"phone": BIA, "message": "chego às 8"}]
    fake.fail_send = "recusado"
    with pytest.raises(GowaError) as refused:
        service.send(BIA, "oi")
    assert not isinstance(refused.value, Uncertain) and "phone inválido" in str(refused.value)
    fake.fail_send = "timeout"
    with pytest.raises(Uncertain):
        service.send(BIA, "oi de novo")


def test_webhook_needs_local_origin_and_valid_signature_and_ignores_groups_and_own_messages(server):
    _, service, _ = server
    seen = []
    service.on_message = lambda jid, name: seen.append((jid, name))

    def post(payload, host="127.0.0.1", secret=None):
        body = json.dumps({"event": "message", "payload": payload}).encode()
        signature = "sha256=" + hmac.new((secret or service.secret).encode(), body, hashlib.sha256).hexdigest()
        return service.webhook(body, signature, host)

    assert post({"chat_id": BIA, "sender_display_name": "Ana Beatriz Lima", "is_from_me": False, "body": "oi"})
    assert not post({"chat_id": BIA, "is_from_me": False}, host="192.168.0.20")
    assert not post({"chat_id": BIA, "is_from_me": False}, secret="chute")
    assert post({"chat_id": GRUPO, "is_from_me": False}) and post({"chat_id": BIA, "is_from_me": True})
    assert seen == [(BIA, "Ana Beatriz Lima")]


def test_server_route_rejects_forged_events(server):
    from fastapi.testclient import TestClient
    from server import create_app
    from tests.test_server import FakeAudio, FakeGate, FakeSpeaker, FakeViv
    _, service, _ = server
    app = create_app(FakeViv(), FakeGate(), FakeAudio(), {"server": {"port": 8765}, "live": {}}, FakeSpeaker(), gowa=service)
    client = TestClient(app, client=("127.0.0.1", 50000))
    body = b'{"event":"message","payload":{}}'
    good = "sha256=" + hmac.new(service.secret.encode(), body, hashlib.sha256).hexdigest()
    assert client.post("/api/whatsapp/evento", content=body, headers={"X-Hub-Signature-256": good}).status_code == 200
    assert client.post("/api/whatsapp/evento", content=body, headers={"X-Hub-Signature-256": "sha256=00"}).status_code == 403
    assert TestClient(create_app(FakeViv(), FakeGate(), FakeAudio(), {"server": {}, "live": {}}, FakeSpeaker())) \
        .post("/api/whatsapp/evento", content=body).status_code == 404


# ---- ferramentas pelo caminho direto -------------------------------------------------------
@pytest.fixture
def tools(server, tmp_path, monkeypatch, events):
    fake, service, _ = server
    registry.load_all()
    people = People(str(tmp_path / "pessoas.json"))
    people.define("Ana Beatriz Lima", apelido="Bia")
    settings = Settings(str(tmp_path / "cfg.json"), {})
    played = []
    ctx = Context({}, people=people, settings=settings, gowa=service, audio=type("A", (), {"play": lambda s, pcm: played.append(pcm)})())
    monkeypatch.setattr(whatsapp, "People", lambda: people)
    monkeypatch.setattr(DRAFTS, "current", None)
    monkeypatch.setattr(whatsapp, "_web_chats", lambda ctx=None: pytest.fail("usou o navegador"))
    return fake, service, ctx, played


@pytest.fixture
def events(monkeypatch):
    from viv.bus import BUS
    seen = []
    monkeypatch.setattr(BUS, "emit", lambda channel, text="", **extra: seen.append((channel, text, extra)))
    return seen


def test_tools_use_the_direct_service_without_a_browser(tools, events):
    fake, service, ctx, _ = tools
    out = registry.call("whatsapp_conversas", {}, ctx)
    assert out.startswith("Bia [contato: Ana Beatriz Lima] (3 nova(s)): 🎤 Áudio")
    opened = registry.call("whatsapp_abrir", {"contato": "Bia"}, ctx)
    assert "conversa com Bia aberta na tela" in opened and "oi amor, vem hoje?" in opened and "[áudio]" in opened
    shown = [extra for channel, _, extra in events if channel == "whatsapp" and extra.get("mode") == "chat"][0]
    assert any(m["imagem"] for m in shown["messages"]) and shown["contact"] == "Ana Beatriz Lima"
    assert not any(path.endswith("/read") for _, path, _, _ in fake.calls), "ler pelo caminho direto não marca como lido"


def test_audio_in_silence_is_transcribed_and_aloud_goes_to_vivs_speakers(tools, monkeypatch):
    fake, service, ctx, played = tools
    heard = []
    monkeypatch.setattr(whatsapp, "transcribe", lambda raw, cfg: heard.append(raw) or "liga pra mim")
    monkeypatch.setattr(direct, "decode_pcm", lambda raw: b"PCM:" + raw)
    assert registry.call("whatsapp_audio", {"contato": "Bia"}, ctx) == "áudio de Bia, ouvido em silêncio: “liga pra mim”"
    assert heard == [b"OggS-fake"] and played == []
    assert "tocando o áudio de Bia" in registry.call("whatsapp_audio", {"contato": "Bia", "modo": "tocar"}, ctx)
    assert played == [b"PCM:OggS-fake"]


def test_send_through_the_direct_service_keeps_the_draft_rules(tools):
    fake, service, ctx, _ = tools
    DRAFTS.write("Ana Beatriz Lima", "chego às 8")
    assert registry.call("whatsapp_enviar", {"contato": "Bia", "mensagem": "chego às 8"}, ctx) == "mensagem enviada para Bia"
    assert registry.call("whatsapp_enviar", {"contato": "Bia", "mensagem": "chego às 8"}, ctx).startswith("esta mensagem já foi enviada")
    assert len(fake.sent) == 1
    DRAFTS.write("Ana Beatriz Lima", "levo o vinho")
    fake.fail_send = "timeout"
    assert "não repita" in registry.call("whatsapp_enviar", {"contato": "Bia", "mensagem": "levo o vinho"}, ctx)
    fake.fail_send = None
    fake.messages[BIA].append({"id": "B9", "content": "levo o vinho", "is_from_me": True, "timestamp": stamp(0)})
    out = registry.call("whatsapp_enviar", {"contato": "Bia", "mensagem": "levo o vinho"}, ctx)
    assert "já tinha chegado" in out and len(fake.sent) == 2, "a tentativa incerta não é repetida"


def test_not_paired_explains_how_to_connect_and_connect_shows_a_qr(tools, events, monkeypatch):
    fake, service, ctx, _ = tools
    fake.logged = False
    out = registry.call("whatsapp_conversas", {}, ctx)
    assert out.startswith("erro:") and "whatsapp_conectar" in out
    monkeypatch.setattr(service, "qr", lambda: ("data:image/png;base64,iVBORw0KGgo=", 30))
    monkeypatch.setattr(service, "watch_login", lambda done, refresh=None, **kw: None)
    assert "QR code na tela" in registry.call("whatsapp_conectar", {}, ctx)
    card = [extra for channel, _, extra in events if channel == "whatsapp" and extra.get("mode") == "conectar"][-1]
    assert card["qr"].startswith("data:image/png;base64,")
    monkeypatch.setattr(service, "pair_code", lambda phone: "ABCD-1234")
    assert "ABCD-1234" in registry.call("whatsapp_conectar", {"modo": "codigo", "telefone": "27999990000"}, ctx)


def test_direct_off_or_failed_falls_back_to_whatsapp_web(tools, monkeypatch):
    fake, service, ctx, _ = tools
    monkeypatch.setattr(whatsapp, "_web_chats", lambda ctx=None: [{"name": "Pela web", "last": "", "unread": 0, "photo": ""}])
    ctx.settings.set("whatsapp.direto", False)
    assert "Pela web" in registry.call("whatsapp_conversas", {}, ctx)
    ctx.settings.set("whatsapp.direto", True)
    service.failed = True
    assert "Pela web" in registry.call("whatsapp_conversas", {}, ctx)


def test_pair_code_accepts_brazilian_numbers_only_when_complete(server):
    fake, service, _ = server
    original = fake.__call__
    asked = []

    def handler(request):
        if request.url.path == "/app/login-with-code":
            asked.append(request.url.params["phone"])
            return httpx.Response(200, json={"results": {"pair_code": "WXYZ-9876"}})
        return original(request)
    service.http = httpx.Client(base_url="http://127.0.0.1:39001", transport=httpx.MockTransport(handler))
    assert service.pair_code("(27) 99999-0000") == "WXYZ-9876" and asked == ["5527999990000"]
    with pytest.raises(ValueError):
        service.pair_code("1234")


def test_install_script_pins_version_and_checksum():
    from scripts import instalar_whatsapp as installer
    assert installer.VERSION == "9.6.0" and len(installer.SHA256) == 64
    assert installer.URL.endswith("whatsapp_9.6.0_windows_amd64.zip")
