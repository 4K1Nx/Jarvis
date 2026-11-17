"""Viv pelo WhatsApp: contatos administradores, /viv bloquear, envio autorizado pela voz,
lembretes que voltam pelo WhatsApp e áudios tocados ou transcritos pela tela."""
from types import SimpleNamespace

import pytest
from google.genai import types

from viv.bus import BUS
from viv.people import People
from viv.reminders import Reminders
from viv.remote import Remote
from viv.safety import Gate
from viv.tools import registry, whatsapp
from viv.tools.registry import Context, tool

CRIS = "5551999990001@s.whatsapp.net"
OUTRO = "5551999990002@s.whatsapp.net"


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


@pytest.fixture
def events(monkeypatch):
    seen = []
    monkeypatch.setattr(BUS, "emit", lambda channel, text="", **extra: seen.append((channel, text, extra)))
    return seen


@pytest.fixture
def sandbox():
    """Ferramentas de teste: uma comum, uma pessoal, uma perigosa e uma perigosa que a voz autoriza."""
    registry.load_all()
    calls = []

    @tool("t_clima", "Comum.", {})
    def clima(ctx=None):
        calls.append(("clima", ctx.origin)); return "sol, 28 graus"

    @tool("t_segredo", "Pessoal.", {}, private=True)
    def segredo(ctx=None):
        calls.append(("segredo", ctx.origin)); return "conversas"

    @tool("t_apagar", "Perigosa.", {"pasta": {"type": "string"}}, dangerous=True)
    def apagar(pasta, ctx=None):
        calls.append(("apagar", pasta)); return f"{pasta} apagada"

    @tool("t_enviar", "Perigosa, a voz autoriza.", {}, dangerous=True, voice=True)
    def enviar(ctx=None):
        calls.append(("enviar", "")); return "enviada"

    yield calls
    for name in ("t_clima", "t_segredo", "t_apagar", "t_enviar"):
        registry._REG.pop(name)


# ---- envio autorizado pela voz ----------------------------------------------------------------
class Voice:
    enrolled, last_score = True, 0.9

    def __init__(self, trusted=True):
        self.ok = trusted

    def trusted(self):
        return self.ok

    def is_owner(self, audio):
        return self.ok

    def stranger_present(self):
        return not self.ok


class Audit:
    def record(self, event, **fields):
        pass


def gate_with(voice):
    clock, told = Clock(), []
    gate = Gate({"safety": {"confirm_timeout_seconds": 30, "dangerous": []}}, Context({}), voice, Audit(),
                told.append, clock, spawn=lambda job: job())
    return gate, clock


def test_owner_voice_asking_to_send_skips_the_card(sandbox, events):
    gate, clock = gate_with(Voice(trusted=True))
    gate.on_user_utterance("pode mandar", None)
    assert gate.submit("t_enviar", {}) == "enviada" and gate.pending is None
    assert gate.submit("t_enviar", {}).startswith("pendente"), "um pedido falado autoriza uma ação só"
    gate.pending = None

    gate.on_user_utterance("manda", None)
    clock.now += 61
    assert gate.submit("t_enviar", {}).startswith("pendente"), "pedido antigo não vale"
    gate.pending = None

    gate.on_user_utterance("envia", None)
    assert gate.submit("t_apagar", {"pasta": "Fotos"}).startswith("pendente"), "só ferramentas marcadas com voice"
    gate.pending = None

    other, _ = gate_with(Voice(trusted=False))
    other.on_user_utterance("envia", None)
    assert other.submit("t_enviar", {}).startswith("pendente"), "sem a voz do dono, o cartão volta"
    assert sandbox == [("enviar", "")]


def test_trusted_owner_reads_without_confirmation(sandbox):
    gate, _ = gate_with(Voice(trusted=True))
    assert gate.submit("t_segredo", {}) == "conversas"


# ---- /viv bloquear e contatos administradores ------------------------------------------------
def make_remote(tmp_path, clock=None):
    return Remote(str(tmp_path / "remoto.json"), clock=clock or Clock())


def test_any_contact_can_block_and_unblock_the_viv(tmp_path, events, monkeypatch):
    remote, sent = make_remote(tmp_path), []
    ctx = Context({}, remote=remote, people=People(str(tmp_path / "pessoas.json")))
    send = lambda jid, text: sent.append((jid, text))
    assert remote.handle(OUTRO, "Rafa", "/viv bloquear", ctx, send)
    assert remote.blocked(OUTRO) and remote.blocked("", "rafa")
    assert sent[-1][0] == OUTRO and sent[-1][1].startswith("Viv: ") and "/viv desbloquear" in sent[-1][1]
    with pytest.raises(RuntimeError, match="não receber mensagens escritas pela Viv"):
        whatsapp.refuse_if_blocked(ctx, "Rafa")
    with pytest.raises(RuntimeError, match="nada foi enviado"):
        whatsapp._send("Rafa", "oi", ctx=ctx)
    assert remote.handle(OUTRO, "Rafa", "/VIV desbloquear", ctx, send) and not remote.blocked(OUTRO)
    whatsapp.refuse_if_blocked(ctx, "Rafa")
    again = make_remote(tmp_path)
    assert not again.blocked(OUTRO)


def test_viv_commands_from_non_admins_are_ordinary_messages(tmp_path, events):
    remote, sent = make_remote(tmp_path), []
    ctx = Context({}, remote=remote)
    assert not remote.handle(OUTRO, "Rafa", "/viv abre o navegador", ctx, lambda j, t: sent.append(t))
    assert not remote.handle(OUTRO, "Rafa", "oi, tudo bem?", ctx, lambda j, t: sent.append(t))
    assert sent == []


def test_admins_lose_owner_only_and_private_tools(tmp_path, sandbox):
    remote = make_remote(tmp_path)
    remote.set_admin(CRIS, "Cris", True)
    tools = remote.tools(remote.admin(CRIS))
    assert {"t_clima", "t_apagar", "reminder_set"} <= tools
    assert not tools & {"t_segredo", "whatsapp_ler", "whatsapp_enviar", "contato_adm", "mensagem_rascunhar",
                        "pessoa_definir", "presente_salvar"}
    remote.set_admin(CRIS, "Cris", True, private=True)
    assert {"t_segredo", "whatsapp_ler"} <= remote.tools(remote.admin(CRIS))
    assert "whatsapp_enviar" not in remote.tools(remote.admin(CRIS))
    remote.set_admin(CRIS, "Cris", False)
    assert remote.admin(CRIS) is None


class Model:
    """Cliente falso do Gemini: devolve as respostas programadas, uma por chamada."""

    def __init__(self, *replies):
        self.replies, self.seen = list(replies), []
        self.models = self

    def generate_content(self, model, contents, config=None):
        self.seen.append((list(contents), config))
        kind, value = self.replies.pop(0)
        if kind == "texto":
            return SimpleNamespace(function_calls=None, text=value, candidates=[])
        call = types.FunctionCall(name=value[0], args=value[1])
        content = types.Content(role="model", parts=[types.Part(function_call=call)])
        return SimpleNamespace(function_calls=[call], text="", candidates=[SimpleNamespace(content=content)])


def run_now(monkeypatch):
    """A conversa roda numa thread; nos testes, roda na hora."""
    import viv.remote as module

    class Now:
        def __init__(self, target, args=(), **_):
            self.target, self.args = target, args

        def start(self):
            self.target(*self.args)
    monkeypatch.setattr(module.threading, "Thread", Now)


def test_admin_talks_to_viv_and_tools_run_on_their_behalf(tmp_path, sandbox, events, monkeypatch):
    run_now(monkeypatch)
    remote, sent = make_remote(tmp_path), []
    remote.set_admin(CRIS, "Cris", True)
    client = Model(("ferramenta", ("t_clima", {})), ("texto", "Tá sol, 28 graus ☀️"))
    ctx = Context({}, client=client, remote=remote)
    assert remote.handle(CRIS, "Cris", "/viv como tá o tempo?", ctx, lambda j, t: sent.append((j, t)))
    assert sandbox == [("clima", CRIS)], "a ferramenta sabe que o pedido veio do WhatsApp da Cris"
    assert sent == [(CRIS, "Viv: Tá sol, 28 graus ☀️")]
    contents, config = client.seen[0]
    names = {d["name"] for d in config["tools"][0]["function_declarations"]}
    assert "t_clima" in names and "whatsapp_enviar" not in names and "t_segredo" not in names
    assert any(e[0] == "card" and "Viv no WhatsApp" in e[1] for e in events), "o pedido aparece na HUD"

    client.replies = [("texto", "De nada!")]
    remote.handle(CRIS, "Cris", "/viv valeu", ctx, lambda j, t: sent.append((j, t)))
    history = client.seen[-1][0]
    assert [c.role for c in history] == ["user", "model", "user"], "a conversa lembra a volta anterior"


def test_admin_confirms_dangerous_actions_from_whatsapp(tmp_path, sandbox, events, monkeypatch):
    run_now(monkeypatch)
    clock = Clock()
    remote, sent = make_remote(tmp_path, clock), []
    remote.set_admin(CRIS, "Cris", True)
    client = Model(("ferramenta", ("t_apagar", {"pasta": "Temp"})))
    ctx = Context({}, client=client, remote=remote)
    send = lambda j, t: sent.append(t)
    remote.handle(CRIS, "Cris", "/viv apaga a pasta Temp", ctx, send)
    assert sandbox == [] and "/viv sim" in sent[-1]
    remote.handle(CRIS, "Cris", "/viv não", ctx, send)
    assert sandbox == [] and "Cancelado" in sent[-1]

    client.replies = [("ferramenta", ("t_apagar", {"pasta": "Temp"})), ("texto", "Pronto, apaguei a Temp.")]
    remote.handle(CRIS, "Cris", "/viv apaga a pasta Temp", ctx, send)
    remote.handle(CRIS, "Cris", "/viv sim", ctx, send)
    assert sandbox == [("apagar", "Temp")] and sent[-1] == "Viv: Pronto, apaguei a Temp."

    client.replies = [("ferramenta", ("t_apagar", {"pasta": "Docs"}))]
    remote.handle(CRIS, "Cris", "/viv apaga Docs", ctx, send)
    clock.now += 121
    remote.handle(CRIS, "Cris", "/viv sim", ctx, send)
    assert sandbox == [("apagar", "Temp")] and "expirado" in sent[-1]


def test_reminder_asked_on_whatsapp_goes_back_to_whatsapp(tmp_path):
    spoken, delivered = [], []
    reminders = Reminders(str(tmp_path / "jobs.json"), spoken.append)
    reminders.deliver = lambda jid, text: delivered.append((jid, text))
    registry.load_all()
    registry.call("reminder_set", {"texto": "ligar pro dentista", "segundos": 1}, Context({}, reminders=reminders, origin=CRIS))
    registry.call("reminder_set", {"texto": "beber água", "segundos": 1}, Context({}, reminders=reminders))
    reminders.run_due(now=10 ** 12)
    assert delivered == [(CRIS, "ligar pro dentista")] and spoken == ["beber água"]


# ---- áudio pela tela ---------------------------------------------------------------------------
class Service:
    installed, failed = True, False

    def __init__(self):
        self.downloads = []

    def wait_ready(self, seconds):
        return True

    def logged_in(self):
        return True

    def download(self, message_id, jid):
        self.downloads.append(message_id)
        return b"ogg"


def test_audio_click_transcribes_once_and_updates_the_screen(monkeypatch, events):
    service, heard = Service(), []
    monkeypatch.setattr(whatsapp, "_HEARD", {})
    monkeypatch.setattr(whatsapp, "transcribe", lambda raw, cfg: heard.append(raw) or "chego às 8")
    ctx = Context({}, gowa=service)
    assert whatsapp.audio_action(ctx, CRIS, "3EB0AUDIO1", "transcrever") == "chego às 8"
    assert whatsapp.audio_action(ctx, CRIS, "3EB0AUDIO1", "transcrever") == "chego às 8"
    assert heard == [b"ogg"] and service.downloads == ["3EB0AUDIO1"]
    shown = [e[2] for e in events if e[0] == "whatsapp"]
    assert shown == [{"mode": "transcricao", "id": "3EB0AUDIO1", "transcricao": "chego às 8"}]
    rows = [{"id": "3EB0AUDIO1", "out": False, "audio": True, "text": "", "author": "Cris"}]
    assert whatsapp.format_messages(rows)[0].endswith("[áudio: “chego às 8”]")
    with pytest.raises(ValueError):
        whatsapp.audio_action(ctx, "../../etc", "3EB0AUDIO1", "transcrever")
    with pytest.raises(ValueError):
        whatsapp.audio_action(ctx, CRIS, "x/../y", "tocar")


def test_yes_to_another_confirmation_never_sends_a_draft(sandbox, events):
    gate, clock = gate_with(Voice(trusted=True))
    shown = {"at": None}
    registry._REG["t_enviar"]["voice"] = lambda args: shown["at"]
    assert gate.submit("t_apagar", {"pasta": "Temp"}).startswith("pendente")
    clock.now += 1
    gate.on_user_utterance("sim", None)                        # responde a confirmação do t_apagar
    shown["at"] = clock.now + 0.5                               # depois, a Viv mostra um rascunho
    clock.now += 1
    assert gate.submit("t_enviar", {}).startswith("pendente"), "o “sim” da outra ação não envia o rascunho"
    gate.pending = None
    gate.on_user_utterance("envia", None)                       # dito antes de o próximo rascunho aparecer
    shown["at"] = clock.now + 0.5
    clock.now += 1
    assert gate.submit("t_enviar", {}).startswith("pendente"), "“envia” dito antes do rascunho não vale para ele"
    gate.pending = None
    gate.on_user_utterance("pode enviar", None)
    assert gate.submit("t_enviar", {}) == "enviada"
    assert sandbox == [("apagar", "Temp"), ("enviar", "")]


class Paired(Service):
    def __init__(self):
        super().__init__()
        self.sent = []

    def resolve(self, contact):
        return "Cris Lima", CRIS

    def canonical(self, jid):
        return jid

    def send(self, jid, text):
        self.sent.append((jid, text))


def test_new_admin_is_told_on_whatsapp_how_to_use_the_viv(tmp_path, events):
    registry.load_all()
    remote, service = make_remote(tmp_path), Paired()
    ctx = Context({}, gowa=service, remote=remote, people=People(str(tmp_path / "pessoas.json")))
    out = registry.call("contato_adm", {"contato": "Cris"}, ctx)
    assert remote.admin(CRIS) and "já avisei" in out and "Não envie outra" in out
    assert len(service.sent) == 1 and service.sent[0][0] == CRIS
    assert service.sent[0][1].startswith("Viv: ") and "/viv" in service.sent[0][1] and "/viv bloquear" in service.sent[0][1]
    registry.call("contato_adm", {"contato": "Cris", "ativo": False}, ctx)
    assert remote.admin(CRIS) is None and "encerrou" in service.sent[-1][1]
    remote.set_blocked(CRIS, "Cris Lima", True)
    out = registry.call("contato_adm", {"contato": "Cris"}, ctx)
    assert len(service.sent) == 2 and "não consegui avisar" in out, "quem bloqueou a Viv não recebe o aviso"


def test_bare_viv_opens_a_conversation_until_viv_encerrar(tmp_path, sandbox, events, monkeypatch):
    run_now(monkeypatch)
    clock = Clock()
    remote, sent = make_remote(tmp_path, clock), []
    remote.set_admin(CRIS, "Cris", True)
    client = Model(("texto", "Tá sol!"), ("texto", "De nada!"))
    ctx = Context({}, client=client, remote=remote)
    send = lambda j, t: sent.append(t)
    assert not remote.handle(CRIS, "Cris", "como tá o tempo?", ctx, send), "sem conversa aberta, é mensagem para o dono"
    assert remote.handle(CRIS, "Cris", "/viv", ctx, send) and "/viv encerrar" in sent[-1]
    assert remote.handle(CRIS, "Cris", "como tá o tempo?", ctx, send) and sent[-1] == "Viv: Tá sol!"
    assert remote.handle(CRIS, "Cris", "parar", ctx, send) and not remote.blocked(CRIS), "“parar” na conversa não bloqueia"
    assert not remote.handle(CRIS, "Cris", "", ctx, send), "foto ou áudio sem texto segue para o dono"
    assert remote.handle(CRIS, "Cris", "/viv encerrar", ctx, send) and "encerrada" in sent[-1]
    assert not remote.handle(CRIS, "Cris", "valeu", ctx, send)
    assert not remote.handle(OUTRO, "Rafa", "/viv", ctx, send), "quem não é administrador não abre conversa"

    remote.handle(CRIS, "Cris", "/viv", ctx, send)
    clock.now += 1801
    assert not remote.handle(CRIS, "Cris", "oi", ctx, send), "meia hora parada encerra a conversa sozinha"


def test_search_results_go_back_in_the_whatsapp_reply(tmp_path, sandbox, events, monkeypatch):
    run_now(monkeypatch)
    remote, sent = make_remote(tmp_path), []
    remote.set_admin(CRIS, "Cris", True)

    @tool("t_pesquisa", "Pesquisa.", {})
    def pesquisa(ctx=None):
        return "Hiroshi: lámen ótimo (https://hiroshi.example)\n[resultados exibidos no painel da tela]"
    try:
        client = Model(("ferramenta", ("t_pesquisa", {})), ("texto", ""), ("texto", "O Hiroshi é o melhor: https://hiroshi.example"))
        ctx = Context({}, client=client, remote=remote)
        remote.handle(CRIS, "Cris", "/viv pesquisa um japonês", ctx, lambda j, t: sent.append(t))
        assert sent == ["Viv: O Hiroshi é o melhor: https://hiroshi.example"], "resposta vazia: pede o texto de novo"
        told = client.seen[1][0][-1].parts[0].function_response.response["result"]
        assert "NÃO vê a tela" in told, "a ferramenta lembra que quem pediu não vê a tela"
        assert "não vê a tela" in client.seen[0][1]["system_instruction"]

        client.replies = [("ferramenta", ("t_pesquisa", {})), ("texto", ""), ("texto", "")]
        remote.handle(CRIS, "Cris", "/viv pesquisa de novo", ctx, lambda j, t: sent.append(t))
        assert sent[-1].startswith("Viv: Aqui está o que encontrei:") and "hiroshi.example" in sent[-1]
        assert "painel da tela" not in sent[-1], "sem as notas internas para o modelo"
    finally:
        registry._REG.pop("t_pesquisa")


def test_search_asked_on_whatsapp_never_opens_tabs_on_the_owners_pc(monkeypatch, events):
    from viv.tools import web
    opened = []
    monkeypatch.setattr(web, "search", lambda q: [{"title": "A", "url": "https://a.example", "body": "x"}])
    monkeypatch.setattr(web.webbrowser, "open", opened.append)
    registry.load_all()
    registry.call("web_search", {"query": "x", "abrir_guias": 2}, Context({}, origin=CRIS))
    assert opened == []
    registry.call("web_search", {"query": "x", "abrir_guias": 1}, Context({}))
    assert opened == ["https://a.example"]
