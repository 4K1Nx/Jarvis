"""Chamada pelo nome, reconhecimento de voz, humor, pessoas, WhatsApp e barra de progresso."""
import asyncio

import numpy as np
import pytest

from tests.fakes import Clock, FakeAudio, FakeConnect, FakeGaps, FakeGate, FakeMemory, FakeWatcher, msg
from viv.audio import AudioIO
from viv.bus import BUS
from viv.live import SAFE_VOICE, State, Viv
from viv.mood import GRACE, HALF_LIFE, Mood
from viv.people import People
from viv.safety import Gate
from viv.speaker import FRESH, LONG, Speaker, TRUST
from viv.tools import registry, whatsapp
from viv.tools.registry import Context, tool
from viv.wake import NameSpotter, WakeWatcher, matches_name

ALIASES = ["Viv", "Vivi", "Vive"]


@pytest.fixture
def events(monkeypatch):
    seen = []
    monkeypatch.setattr(BUS, "emit", lambda channel, text="", **extra: seen.append((channel, text, extra)))
    return seen


# ---- chamada ---------------------------------------------------------------
@pytest.mark.parametrize("text", ["Ei, vif", "hey viva", "Eivive, tudo bem?", "oi bibi", "acorda vivo", "Ei, Vív!"])
def test_name_misheard_after_a_call_word_still_wakes(text):
    assert matches_name(text, ALIASES)


@pytest.mark.parametrize("text", ["viva o Brasil", "eu vivo aqui", "ei, vou viver bem", "oi, vivendo e aprendendo",
                                  "ei, você viu?", "que vibe boa"])
def test_ordinary_speech_does_not_wake(text):
    assert not matches_name(text, ALIASES)


def loud(ms, amp=0.3):
    t = np.arange(int(16000 * ms / 1000)) / 16000
    wave = (np.sin(2 * np.pi * 200 * t) * amp * 32767).astype(np.int16).tobytes()
    return [wave[i:i + 640] for i in range(0, len(wave) - 639, 640)]


QUIET = [bytes(640)] * 20


def test_a_bare_viv_of_a_quarter_second_is_transcribed():
    heard = []
    spotter = NameSpotter(ALIASES, lambda audio: heard.append(len(audio)) or "viv")
    fired = [spotter.feed(frame, i * 0.02) for i, frame in enumerate(loud(240) + QUIET)]
    assert any(fired) and heard, "um “Viv” curto era descartado antes de chegar ao transcritor"


class Frames:
    def __init__(self, frames):
        self.frames = list(frames)

    def read(self, timeout=0.1):
        return self.frames.pop(0) if self.frames else None


def test_watcher_keeps_the_call_audio_for_the_conversation_once():
    woke = []
    frames = loud(400) + QUIET
    watcher = WakeWatcher({"wake": {"aliases": ALIASES, "clap_enabled": False}}, Frames(frames), woke.append,
                          transcribe=lambda audio: "ei viv que horas são")
    for _ in frames:
        watcher.run_once()
    assert woke == ["name"]
    heard = watcher.take_heard()
    assert len(heard) >= 640 * 20 and watcher.take_heard() == b""


# ---- reconhecimento de voz ------------------------------------------------------
OWNER = np.array([1.0, 0.0, 0.0], dtype=np.float32)
ANA = np.array([0.0, 1.0, 0.0], dtype=np.float32)
OTHER = np.array([0.0, 0.0, 1.0], dtype=np.float32)


def make_speaker(tmp_path, voices):
    """Speaker com o encoder trocado: o primeiro valor do áudio escolhe de quem é a voz."""
    clock = Clock()
    spk = Speaker({"speaker_id": {"voiceprint_path": str(tmp_path / "dono.json"),
                                  "people_path": str(tmp_path / "outros.json")}}, clock=clock)
    spk._embed = lambda audio: voices[int(round(float(audio[0])))]
    spk.enroll([np.zeros(LONG, dtype=np.float32)], "Gabriel")
    return spk, clock


def clip(voice, samples=LONG):
    return np.full(samples, float(voice), dtype=np.float32)


def test_speaker_identifies_owner_other_person_and_stranger(tmp_path, events):
    spk, _ = make_speaker(tmp_path, [OWNER, ANA, OTHER])
    spk.enroll_person([clip(1)], "Ana")
    assert spk.hear(clip(0)) == {"name": "Gabriel", "owner": True, "known": True, "heard": True}
    assert spk.hear(clip(1)) == {"name": "Ana", "owner": False, "known": True, "heard": True}
    assert spk.stranger_present(), "outra pessoa cadastrada falando: WhatsApp e e-mail pedem confirmação"
    assert spk.hear(clip(2)) == {"name": "", "owner": False, "known": False, "heard": True}
    assert not spk.stranger_present(), "voz só não reconhecida não trava a leitura"
    assert [e[1] for e in events if e[0] == "speaker"] == ["Gabriel", "Ana", ""]


def test_other_people_are_saved_apart_and_survive_restart(tmp_path):
    spk, _ = make_speaker(tmp_path, [OWNER, ANA])
    owner_file = (tmp_path / "dono.json").read_bytes()
    spk.enroll_person([clip(1)], "Ana")
    assert (tmp_path / "dono.json").read_bytes() == owner_file
    again = Speaker({"speaker_id": {"voiceprint_path": str(tmp_path / "dono.json"),
                                    "people_path": str(tmp_path / "outros.json")}})
    assert again.owner == "Gabriel" and list(again.people) == ["Ana"]


def test_short_yes_counts_only_right_after_the_owner_spoke(tmp_path):
    almost = np.array([0.7, 0.714, 0.0], dtype=np.float32)        # 0,70 de semelhança: passa só no limiar curto
    spk, clock = make_speaker(tmp_path, [OWNER, almost, OTHER])
    short = clip(1, 6000)
    assert not spk.is_owner(short), "sem o dono reconhecido antes, um “sim” curto não confirma"
    assert not spk.is_owner(clip(1)), "fala longa precisa passar no limiar cheio"


def test_owner_voice_keeps_permissions_for_five_minutes(tmp_path):
    almost = np.array([0.7, 0.714, 0.0], dtype=np.float32)
    spk, clock = make_speaker(tmp_path, [OWNER, almost, OTHER])
    spk.hear(clip(0))
    assert spk.trusted() and spk.is_owner(clip(2, 6000)), "na janela de confiança, o “sim” curto vale"
    clock.now += FRESH + 1
    spk.hear(clip(1))                                             # fala um pouco abaixo do limiar: ruído, fone
    assert spk.trusted() and not spk.stranger_present(), "fala quase igual à do dono não derruba a confiança"
    spk.hear(clip(2))                                             # voz bem diferente da do dono
    assert not spk.trusted() and not spk.is_owner(clip(1, 6000))
    spk.hear(clip(0))
    clock.now += TRUST + 1
    assert not spk.trusted() and not spk.is_owner(clip(1, 6000))


def test_too_little_speech_keeps_the_previous_identity(tmp_path):
    spk, _ = make_speaker(tmp_path, [OWNER, OTHER])
    spk.hear(clip(0))
    assert spk.hear(clip(1, 8000))["owner"]


def test_turn_speech_excludes_silence_and_is_handed_over_once():
    audio = AudioIO({})
    voiced = loud(200)
    for frame in voiced + QUIET:
        assert audio.should_send(frame)
    speech = audio.take_speech()
    assert len(speech) == len(voiced) * 320 and len(audio.take_speech()) == 0


# ---- portão: humor, conteúdo pessoal e confirmação vencida ---------------------------
class Audit:
    def __init__(self):
        self.events = []

    def record(self, event, **fields):
        self.events.append((event, fields))


class Voice:
    enrolled, last_score = True, 0.0

    def __init__(self, stranger=False, owner=True):
        self.stranger, self.owner = stranger, owner

    def is_owner(self, audio):
        return self.owner

    def stranger_present(self):
        return self.stranger


@pytest.fixture
def tools():
    calls = []

    @tool("t_abrir", "Comum.", {})
    def abrir(ctx=None):
        calls.append("abrir"); return "aberto"

    @tool("t_mensagens", "Pessoal.", {}, private=True)
    def mensagens(ctx=None):
        calls.append("mensagens"); return "3 mensagens"

    @tool("t_apagar", "Perigosa.", {}, dangerous=True)
    def apagar(ctx=None):
        calls.append("apagar"); return "apagado"

    @tool("config_teste", "Ajuste.", {})
    def ajuste(ctx=None):
        calls.append("ajuste"); return "ajustado"

    yield calls
    for name in ("t_abrir", "t_mensagens", "t_apagar", "config_teste"):
        registry._REG.pop(name)


def make_gate(voice=None, mood=None):
    clock, told = Clock(), []
    gate = Gate({"safety": {"confirm_timeout_seconds": 30, "dangerous": []}}, Context({}), voice or Voice(), Audit(),
                told.append, clock)
    gate.mood = mood
    return gate, clock, told


def angry(tmp_path, clock=None, chance=lambda: 0.0, **options):
    mood = Mood(str(tmp_path / "humor.json"), clock=clock or Clock(), chance=chance, **options)
    mood.feel("ofensa"); mood.feel("ofensa")
    return mood


def test_bad_mood_refuses_once_then_obeys(tmp_path, tools, events):
    clock = Clock()
    mood = angry(tmp_path, clock)
    assert mood.name == "irritada"
    gate, _, _ = make_gate(mood=mood)
    assert gate.submit("t_abrir", {}).startswith("humor:") and tools == []
    assert gate.submit("t_abrir", {}) == "aberto", "insistir sempre funciona"
    assert gate.submit("t_abrir", {}) == "aberto"
    assert tools == ["abrir", "abrir"]
    mood.feel("ofensa"); mood.feel("ofensa")
    clock.now += GRACE + 1
    assert gate.submit("t_abrir", {}).startswith("humor:"), "passado o intervalo, o mau humor pode recusar de novo"


def test_bad_mood_never_refuses_settings_and_can_be_switched_off(tmp_path, tools, events):
    mood = angry(tmp_path)
    gate, _, _ = make_gate(mood=mood)
    assert gate.submit("config_teste", {}) == "ajustado"
    mood.configure(refusals=False)
    assert gate.submit("t_abrir", {}) == "aberto"
    assert mood.name == "irritada" and "humor:" not in mood.prompt()
    mood.configure(enabled=False)
    assert mood.name == "serena" and mood.prompt() == "" and mood.state()["enabled"] is False


def test_good_mood_never_refuses(tmp_path, tools, events):
    mood = Mood(str(tmp_path / "humor.json"), chance=lambda: 0.0)
    gate, _, _ = make_gate(mood=mood)
    assert mood.name == "serena" and gate.submit("t_abrir", {}) == "aberto"


def test_private_tool_asks_confirmation_only_when_a_stranger_speaks(tools, events):
    gate, _, _ = make_gate(Voice(stranger=False))
    assert gate.submit("t_mensagens", {}) == "3 mensagens"
    gate, _, told = make_gate(Voice(stranger=True, owner=False))
    assert gate.submit("t_mensagens", {}).startswith("pendente") and tools == ["mensagens"]
    gate.on_user_utterance("sim", np.zeros(8000, dtype=np.float32))
    assert gate.pending is not None, "a voz de um estranho não libera o conteúdo pessoal"
    gate.on_click(True)
    assert tools == ["mensagens", "mensagens"] and "3 mensagens" in told[0]


def test_expired_confirmation_does_not_block_the_next_request(tools, events):
    gate, clock, told = make_gate()
    assert gate.submit("t_apagar", {}).startswith("pendente") and gate.remaining() == 30
    clock.now += 31                     # ninguém chamou tick(): a conversa caiu com o pedido pendente
    assert gate.submit("t_apagar", {}).startswith("pendente"), "o pedido vencido travava todos os seguintes"
    assert "cancelada" in told[0] and ("confirm_done", "", {"ok": False}) in events
    assert gate.remaining() == 30


# ---- humor -----------------------------------------------------------------------
def test_mood_follows_what_happens_and_settles_back(tmp_path, events):
    clock = Clock()
    mood = Mood(str(tmp_path / "humor.json"), clock=clock)
    assert mood.name == "serena"
    mood.hear("Você é incrível, obrigado!"); mood.hear("mandou bem")
    assert mood.name == "radiante"
    for _ in range(4):                  # de radiante, o caminho até irritada passa por serena e impaciente
        mood.hear("cala a boca, sua burra")
    assert mood.name == "irritada"
    assert Mood(str(tmp_path / "humor.json"), clock=clock).name == "irritada", "o humor sobrevive a reiniciar"
    mood.hear("desculpa, foi mal")
    assert mood.name == "irritada", "um pedido de desculpa não apaga quatro ofensas"
    mood.hear("me perdoa")
    assert mood.name == "impaciente"
    clock.now += HALF_LIFE * 8
    assert mood.name == "serena"
    names = [e[2]["name"] for e in events if e[0] == "mood"]
    assert names[0] == "radiante" and "impaciente" in names and "irritada" in names and names[-1] == "serena"
    assert all(len(e[2]["palette"]) == 3 for e in events if e[0] == "mood")


def test_tiredness_comes_from_late_hours_and_long_work(tmp_path, events):
    mood = Mood(str(tmp_path / "humor.json"), clock=Clock())
    mood.feel("madrugada"); mood.feel("madrugada")
    assert mood.name == "cansada" and "cansada" in mood.prompt()


# ---- pessoas -----------------------------------------------------------------------
def test_people_are_known_by_nickname_and_relation(tmp_path):
    people = People(str(tmp_path / "pessoas.json"))
    people.define("Maria Silva", apelido="Mãe", relacao="mãe do usuário")
    people.define("Carlos Souza Trabalho", relacao="chefe")
    people.define("Maria Silva", notas="liga todo domingo")
    again = People(str(tmp_path / "pessoas.json"))
    assert again.resolve("mae") == "Maria Silva" and again.resolve("o chefe") == "Carlos Souza Trabalho"
    assert again.resolve("Fulano") == "Fulano"
    assert again.label("Maria Silva") == "Mãe" and again.label("Carlos Souza Trabalho") == "chefe"
    assert again.find("Mãe")["notas"] == "liga todo domingo"
    assert "Mãe: contato “Maria Silva”" in again.prompt_block()
    assert again.forget("mãe") and again.resolve("mãe") == "mãe" and len(again.all()) == 1


# ---- WhatsApp (sem navegador) ---------------------------------------------------------
def test_whatsapp_chat_list_is_deduplicated_and_counts_unread():
    rows = [{"name": "Maria Silva", "last": "Chegou bem?", "unread": "2"},
            {"name": "Maria Silva", "last": "Chegou bem?", "unread": "2"},
            {"name": "", "last": "x", "unread": ""},
            {"name": "Grupo da Família", "last": "foto", "unread": "2 mensagens não lidas"},
            {"name": "Carlos", "last": "ok", "unread": ""}]
    rows[0]["photo"] = "https://pps.whatsapp.net/v/foto.jpg"
    rows[4]["photo"] = "javascript:alert(1)"
    assert whatsapp.clean_chats(rows) == [
        {"name": "Maria Silva", "last": "Chegou bem?", "unread": 2, "photo": "https://pps.whatsapp.net/v/foto.jpg", "group": False, "mine": False, "novas": []},
        {"name": "Grupo da Família", "last": "foto", "unread": 2, "photo": "", "group": False, "mine": False, "novas": []},
        {"name": "Carlos", "last": "ok", "unread": 0, "photo": "", "group": False, "mine": False, "novas": []}]
    mine = whatsapp.clean_chats([{"name": "Bia", "last": "Você: chego às 8", "unread": "1", "mine": True}])[0]
    assert mine["mine"] and mine["unread"] == 0, "conversa em que o usuário falou por último nunca é pendente"


def test_whatsapp_picks_only_an_unambiguous_chat():
    names = ["Ana", "Ana Paula", "Carlos Souza", "Mãe ❤"]
    assert whatsapp.pick_chat(names, "ana") == "Ana"
    assert whatsapp.pick_chat(names, "carlos") == "Carlos Souza"
    assert whatsapp.pick_chat(names, "mae") == "Mãe ❤"
    assert whatsapp.pick_chat(["Ana Paula", "Ana Clara"], "ana") is None
    assert whatsapp.pick_chat(names, "") is None and whatsapp.pick_chat(names, "Bruno") is None


def test_whatsapp_messages_are_formatted_with_time_and_author():
    rows = [{"out": False, "meta": "[14:02, 12/11/2026] Maria Silva: ", "text": "Oi filho,\n tudo bem?"},
            {"out": True, "meta": "[14:05, 12/11/2026] Gabriel: ", "text": "Tudo!"},
            {"out": False, "meta": "", "text": ""}]
    assert whatsapp.format_messages(rows) == ["14:02 Maria Silva: Oi filho, tudo bem?", "14:05 Você: Tudo!",
                                              "Contato: [mídia ou mensagem sem texto]"]


def test_whatsapp_send_is_dangerous_and_the_card_shows_the_real_contact(tmp_path, monkeypatch):
    registry.load_all()
    people = People(str(tmp_path / "pessoas.json"))
    people.define("Maria Silva", apelido="Mãe")
    monkeypatch.setattr(whatsapp, "People", lambda: people)
    assert registry.is_dangerous("whatsapp_enviar", {})
    assert registry.is_private("whatsapp_ler") and registry.is_private("whatsapp_conversas")
    with pytest.raises(ValueError, match="rascunho"):
        registry.confirm_text("whatsapp_enviar", {"contato": "mãe", "mensagem": "Chego  às 8"})
    monkeypatch.setattr(whatsapp.DRAFTS, "current", {"contato": "Maria Silva", "texto": "Chego às 8", "estado": "rascunho"})
    assert registry.confirm_text("whatsapp_enviar", {"contato": "mãe", "mensagem": "Chego  às 8"}) == \
        "Enviar WhatsApp para Maria Silva (Mãe): “Chego às 8”"
    with pytest.raises(ValueError):
        registry.confirm_text("whatsapp_enviar", {"contato": "mãe", "mensagem": "  "})


# ---- barra de progresso ---------------------------------------------------------------
def test_every_tool_reports_progress_and_always_closes_it(events):
    @tool("t_passos", "Demorada.", {"falhar": {"type": "boolean"}}, title="Tarefa longa")
    def passos(falhar, ctx=None):
        registry.progress("Lendo a fonte 1 de 2", 0.5)
        if falhar:
            raise RuntimeError("caiu")
        return "pronto"

    try:
        assert registry.call("t_passos", {"falhar": False}, Context({})) == "pronto"
        assert registry.call("t_passos", {"falhar": True}, Context({})) == "erro: caiu"
    finally:
        registry._REG.pop("t_passos")
    progress = [(text, extra["value"], extra["done"]) for channel, text, extra in events if channel == "progress"]
    assert progress == [("Tarefa longa", None, False), ("Lendo a fonte 1 de 2", 0.5, False), ("", None, True)] * 2


# ---- conversa ---------------------------------------------------------------------------
CFG = {"assistant": {"name": "Viv", "idle_seconds": 60, "history_turns": 12},
       "live": {"model": "m", "voice": "Achernar", "language": "pt-BR"}, "safety": {"dangerous": []}}


class HeardWatcher(FakeWatcher):
    def __init__(self, heard=b""):
        super().__init__()
        self.heard = heard

    def take_heard(self):
        heard, self.heard = self.heard, b""
        return heard


class Who:
    enrolled, owner, people = True, "Gabriel", {"Ana": None}

    def __init__(self):
        self.heard, self.name = [], ""

    def hear(self, audio):
        self.heard.append(len(audio))
        self.name = "Gabriel"

    def who(self):
        return {"name": self.name, "owner": self.name == "Gabriel", "known": bool(self.name), "heard": bool(self.name)}


async def run_viv(viv, body):
    task = asyncio.create_task(viv.run())
    try:
        await body()
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def until(cond, timeout=2.0):
    end = asyncio.get_running_loop().time() + timeout
    while not cond():
        assert asyncio.get_running_loop().time() < end, "condição não atingida a tempo"
        await asyncio.sleep(0.01)


async def test_call_audio_reaches_the_model_and_names_who_called(tmp_path, events):
    heard = b"\x01\x02" * 8000                                   # 1 s de áudio da chamada
    audio, connect, who = FakeAudio(), FakeConnect(), Who()
    mood = Mood(str(tmp_path / "humor.json"))
    viv = Viv(dict(CFG), audio, FakeGate(), FakeMemory(), HeardWatcher(heard), connect, gaps=FakeGaps(),
              speaker=who, mood=mood, people=People(str(tmp_path / "pessoas.json")))

    async def body():
        viv.wake("name")
        await until(lambda: viv.state == State.LISTENING and connect.sessions)
        assert audio.beeps == ["wake"] and who.heard == [8000]
        assert b"".join(connect.session.sent_audio)[:len(heard)] == heard
        instruction = connect.configs[0]["system_instruction"]
        assert "Quem chamou você agora: Gabriel" in instruction and "Outras vozes cadastradas: Ana" in instruction
        assert "Seu humor agora: serena" in instruction
        assert "nunca recuse um pedido por causa da voz" in instruction
    await run_viv(viv, body)


async def test_wake_is_acknowledged_before_the_connection_opens(events):
    audio, states = FakeAudio(), []

    def connect(config):
        states.append((list(audio.beeps), [e[2].get("state") for e in events if e[0] == "state"][-1]))
        return FakeConnect()(config)
    viv = Viv(dict(CFG), audio, FakeGate(), FakeMemory(), FakeWatcher(), connect, gaps=FakeGaps())

    async def body():
        viv.wake("name")
        await until(lambda: bool(states))
        assert states[0] == (["wake"], "thinking")
    await run_viv(viv, body)


async def test_unavailable_voice_falls_back_instead_of_going_mute(events):
    connect = FakeConnect([RuntimeError("400 INVALID_ARGUMENT: voice Achernar is not supported")])
    cfg = {**CFG, "live": dict(CFG["live"])}
    viv = Viv(cfg, FakeAudio(), FakeGate(), FakeMemory(), FakeWatcher(), connect, gaps=FakeGaps())

    async def body():
        viv.wake("button")
        await until(lambda: viv.state == State.LISTENING and connect.sessions)
        voices = [c["speech_config"]["voice_config"]["prebuilt_voice_config"]["voice_name"] for c in connect.configs]
        assert voices == ["Achernar", SAFE_VOICE] and cfg["live"]["voice"] == SAFE_VOICE
        assert any(e[0] == "card" and "indisponível" in e[1] for e in events)
    await run_viv(viv, body)


async def test_speaker_change_reaches_the_model_inside_a_tool_result(events):
    connect, who, gate = FakeConnect(), Who(), FakeGate()
    viv = Viv(dict(CFG), FakeAudio(), gate, FakeMemory(), FakeWatcher(), connect, gaps=FakeGaps(), speaker=who)

    async def body():
        viv.wake("button")
        await until(lambda: viv.state == State.LISTENING and connect.sessions)
        session = connect.session
        session.push(msg(input_text="abre o chrome", input_finished=True),
                     msg(tool_calls=[("1", "desktop_launch_app", {"name": "chrome"})]))
        await until(lambda: session.tool_responses)
        assert session.tool_responses[0].response["result"].endswith("[contexto: quem fala agora: Gabriel]")
        session.push(msg(tool_calls=[("2", "desktop_launch_app", {"name": "chrome"})]))
        await until(lambda: len(session.tool_responses) == 2)
        assert "contexto" not in session.tool_responses[1].response["result"], "só avisa quando muda"
    await run_viv(viv, body)


async def test_model_is_never_told_to_refuse_when_the_voice_is_not_identified_yet(events):
    """Acordada por palmas ou atalho, ela ainda não ouviu ninguém: o modelo recusava os pedidos
    pessoais do próprio dono. Quem barra um estranho é o portão, na hora da ferramenta."""
    connect, who = FakeConnect(), Who()
    viv = Viv(dict(CFG), FakeAudio(), FakeGate(), FakeMemory(), FakeWatcher(), connect, gaps=FakeGaps(), speaker=who)

    async def body():
        viv.wake("clap")
        await until(lambda: viv.state == State.LISTENING and connect.sessions)
        instruction = connect.configs[0]["system_instruction"]
        assert "não reconhece" not in instruction.replace("nem diga que não reconhece a voz de alguém", "")
        assert "ainda não identificado" not in instruction and "não revele" not in instruction
        assert "chame a ferramenta pedida" in instruction
    await run_viv(viv, body)


# ---- WhatsApp: abrir conversa, áudio e fotos ---------------------------------------------------
class FakeLocator:
    def __init__(self, page, selector):
        self.page, self.selector = page, selector
        self.first = self.last = self

    def evaluate_all(self, script):
        return list(self.page.titles)

    def click(self, timeout=None):
        if self.selector in self.page.missing:
            raise TimeoutError(self.selector)
        self.page.clicks.append(self.selector)


class FakePage:
    def __init__(self, titles, after_search=None, missing=(), editable=True):
        self.titles, self.after_search, self.missing, self.editable = titles, after_search, set(missing), editable
        self.clicks, self.keys, self.typed = [], [], []
        self.keyboard = self

    def locator(self, selector):
        return FakeLocator(self, selector)

    def press(self, key):
        self.keys.append(key)

    def type(self, text, delay=0):
        self.typed.append(text)
        if self.after_search is not None:
            self.titles = self.after_search

    def evaluate(self, script, arg=None):
        return self.editable

    def wait_for_timeout(self, ms):
        pass

    def wait_for_selector(self, selector, timeout=None):
        pass


def test_chat_in_the_recent_list_opens_with_one_click_and_no_search():
    page = FakePage(["Maria Silva", "Carlos Souza"])
    assert whatsapp._open_chat(page, "maria silva") == "Maria Silva"
    assert page.clicks == ['#pane-side span[title="Maria Silva"]'] and page.typed == []


def test_search_survives_whatsapp_changing_the_search_field():
    """O erro real: o campo de busca antigo sumiu e a leitura morria num tempo esgotado de 15 s."""
    page = FakePage(["Carlos Souza"], after_search=["Ana Beatriz Lima"], missing=whatsapp.SEARCH[:3])
    assert whatsapp._open_chat(page, "Ana Beatriz Lima") == "Ana Beatriz Lima"
    assert page.clicks == [whatsapp.SEARCH[3], '#pane-side span[title="Ana Beatriz Lima"]'] and page.typed == ["Ana Beatriz Lima"]
    page = FakePage(["Carlos Souza"], after_search=["Ana Beatriz Lima"], missing=whatsapp.SEARCH)
    assert whatsapp._open_chat(page, "Ana Beatriz Lima") == "Ana Beatriz Lima" and "Control+Alt+/" in page.keys
    page = FakePage(["Carlos Souza"], missing=whatsapp.SEARCH, editable=False)
    with pytest.raises(RuntimeError, match="lista recente"):
        whatsapp._open_chat(page, "Ana Beatriz Lima")


def test_messages_keep_audio_and_only_embedded_thumbnails():
    pixel = "data:image/png;base64,iVBORw0KGgo="
    rows = [{"out": False, "meta": "", "time": "09:15", "text": "", "audio": True, "image": ""},
            {"out": False, "meta": "[09:16, 13/11/2026] Ana: ", "text": "olha", "audio": False, "image": pixel},
            {"out": True, "meta": "[09:17, 13/11/2026] Eu: ", "text": "kkk boa", "audio": False, "image": "https://x.example/a.png"}]
    clean = whatsapp.clean_messages(rows)
    assert clean[0] == {"out": False, "autor": "Contato", "hora": "09:15", "texto": "", "audio": True, "imagem": "",
                        "id": "", "transcricao": ""}
    assert clean[1]["imagem"] == pixel and clean[2]["imagem"] == "" and clean[2]["autor"] == "Você"
    assert whatsapp.format_messages(rows) == ["09:15 Contato: [áudio]", "09:16 Ana: olha", "09:17 Você: kkk boa"]


def test_reply_style_comes_from_the_users_own_messages_in_that_chat(tmp_path, monkeypatch, events):
    registry.load_all()
    people = People(str(tmp_path / "pessoas.json"))
    people.define("Ana Beatriz Lima", apelido="Bia")
    monkeypatch.setattr(whatsapp, "_MINE", {})
    rows = [{"out": False, "meta": "[09:16, 13/11/2026] Ana: ", "text": "vem hoje?"},
            {"out": True, "meta": "[09:17, 13/11/2026] Eu: ", "text": "vou sim amor 😘"}]
    monkeypatch.setattr(whatsapp, "_read", lambda contact, limit, images=4, ctx=None: ("Ana Beatriz Lima", rows))
    ctx = Context({}, people=people)
    assert "Como o usuário escreve" not in registry.call("mensagem_preparar", {"contato": "Bia"}, ctx)
    out = registry.call("whatsapp_abrir", {"contato": "Bia"}, ctx)
    assert out.startswith("conversa com Bia aberta na tela") and "vem hoje?" in out
    shown = next(extra for channel, text, extra in events if channel == "whatsapp")
    assert shown["mode"] == "chat" and shown["contact"] == "Ana Beatriz Lima" and len(shown["messages"]) == 2
    prepared = registry.call("mensagem_preparar", {"contato": "Bia"}, ctx)
    assert "vou sim amor 😘" in prepared and "do jeito dele" in prepared and "formal" in prepared


def test_chat_list_puts_pending_first_and_tells_the_hud(tmp_path, monkeypatch, events):
    registry.load_all()
    people = People(str(tmp_path / "pessoas.json"))
    people.define("Maria Silva", apelido="Mãe")
    chats = [{"name": "Carlos", "last": "ok", "unread": 0, "photo": ""},
             {"name": "Maria Silva", "last": "Chegou bem?", "unread": 2, "photo": ""}]
    monkeypatch.setattr(whatsapp, "_chats", lambda ctx=None: [dict(c) for c in chats])
    out = registry.call("whatsapp_conversas", {}, Context({}, people=people))
    assert out.startswith("- Mãe [contato: Maria Silva]: 2 mensagem(ns) nova(s)") and "- Carlos: nada novo; última: ok" in out
    assert "uma por uma" in out
    shown = next(extra for channel, text, extra in events if channel == "whatsapp")
    assert shown["mode"] == "lista" and [c["label"] for c in shown["chats"]] == ["Mãe", "Carlos"]


def test_audio_is_heard_silently_or_played_aloud(tmp_path, monkeypatch, events):
    registry.load_all()
    people = People(str(tmp_path / "pessoas.json"))
    people.define("Maria Silva", apelido="Mãe")
    calls = []

    def audio(contact, which, silent, ctx=None):
        calls.append((contact, which, silent))
        return "Maria Silva", b"ogg" if silent else b"", "3EB0AUDIO1"
    monkeypatch.setattr(whatsapp, "_audio", audio)
    monkeypatch.setattr(whatsapp, "transcribe", lambda data, cfg: "liga pra mim quando puder")
    ctx = Context({}, people=people)
    assert registry.call("whatsapp_audio", {"contato": "mãe"}, ctx) == "áudio de Mãe, ouvido em silêncio: “liga pra mim quando puder”"
    assert "tocando o áudio de Mãe" in registry.call("whatsapp_audio", {"contato": "mãe", "modo": "tocar", "qual": 2}, ctx)
    assert calls == [("Maria Silva", 1, True), ("Maria Silva", 2, False)]
    assert registry.is_private("whatsapp_audio") and registry.is_private("whatsapp_abrir")


# ---- remetente certo, sincronia da fala, avisos e boas-vindas --------------------------------
def test_listing_tells_who_sent_each_message(tmp_path):
    people = People(str(tmp_path / "p.json"))
    people.define("Maria Silva", apelido="Mãe")
    chats = whatsapp.prepare(whatsapp.clean_chats([
        {"name": "Maria Silva", "last": "Me liga", "unread": 2, "novas": [{"texto": "Chegou?"}, {"texto": "Me liga"}]},
        {"name": "Ana Beatriz Lima", "last": "Você: chego às 8", "mine": True},
        {"name": "Família", "group": True, "last": "Tio Zé: foto", "unread": 1, "novas": [{"autor": "Tio Zé", "texto": "📷 Foto"}]},
    ]), people)
    text = whatsapp.listing(chats)
    assert "- Mãe [contato: Maria Silva]: 2 mensagem(ns) nova(s) que a pessoa mandou para o usuário: “Chegou?”; “Me liga”" in text
    assert "- Ana Beatriz Lima: a última mensagem é DO USUÁRIO (“chego às 8”); a outra pessoa ainda não respondeu" in text
    assert "- Família (grupo): 1 mensagem(ns) nova(s) no grupo: Tio Zé: “📷 Foto”" in text
    assert chats[0]["aliases"] == ["Mãe", "Maria Silva", "Maria"] and chats[2]["aliases"] == ["Família"]


def test_first_name_is_an_alias_only_when_unique(tmp_path):
    chats = whatsapp.prepare(whatsapp.clean_chats([{"name": "Ana Paula"}, {"name": "Ana Clara"}, {"name": "Bruno Lima"}]),
                             People(str(tmp_path / "p.json")))
    assert chats[0]["aliases"] == ["Ana Paula"] and chats[2]["aliases"] == ["Bruno Lima", "Bruno"]


class PlayingAudio(FakeAudio):
    """Caixa de som que toca devagar: dá para ver a legenda esperar o áudio."""

    def __init__(self):
        super().__init__()
        self.queued = self.played = 0

    def play(self, pcm):
        self.queued += len(pcm)
        self.playing = True

    def position(self):
        return self.queued, self.played


async def test_captions_follow_the_audio_instead_of_running_ahead(events):
    audio, connect = PlayingAudio(), FakeConnect()
    viv = Viv(dict(CFG), audio, FakeGate(), FakeMemory(), FakeWatcher(), connect, gaps=FakeGaps())

    def said():
        return [text for channel, text, extra in events if channel == "transcript" and extra.get("role") == "viv"]

    async def body():
        viv.wake("button")
        await until(lambda: viv.state == State.LISTENING and connect.sessions)
        session = connect.session
        session.push(msg(data=b"m" * 4800), msg(output_text="Sua mãe perguntou se você chegou."),
                     msg(data=b"b" * 4800), msg(output_text=" A Bia mandou uma foto."), msg(turn_complete=True))
        await until(lambda: audio.queued == 9600)
        await asyncio.sleep(0.15)
        assert said() == ["Sua mãe perguntou se você chegou."], "a frase sobre a Bia esperou o áudio dela"
        audio.played = 4800                          # começou a tocar o trecho da Bia
        await until(lambda: len(said()) == 2)
        assert said()[-1] == "Sua mãe perguntou se você chegou. A Bia mandou uma foto."
        audio.played, audio.playing = 9600, False    # terminou de falar
        await until(lambda: any(extra.get("final") for c, _, extra in events if c == "transcript" and extra.get("role") == "viv"))
    await run_viv(viv, body)


async def test_interruption_releases_pending_captions_at_once(events):
    audio, connect = PlayingAudio(), FakeConnect()
    viv = Viv(dict(CFG), audio, FakeGate(), FakeMemory(), FakeWatcher(), connect, gaps=FakeGaps())

    async def body():
        viv.wake("button")
        await until(lambda: viv.state == State.LISTENING and connect.sessions)
        session = connect.session
        session.push(msg(data=b"x" * 4800), msg(output_text="Primeira."), msg(data=b"y" * 4800), msg(output_text=" Segunda."))
        await asyncio.sleep(0.15)
        session.push(msg(interrupted=True))
        await until(lambda: any(t.endswith("Segunda.") for c, t, _ in events if c == "transcript"))
    await run_viv(viv, body)


async def test_new_message_is_spoken_only_while_awake(events):
    connect = FakeConnect()
    viv = Viv(dict(CFG), FakeAudio(), FakeGate(), FakeMemory(), FakeWatcher(), connect, gaps=FakeGaps())

    async def body():
        assert viv.mention("mensagem nova de Mãe") is False, "dormindo: nada a falar"
        await asyncio.sleep(0.05)
        assert viv.state == State.SLEEPING and not connect.configs, "o aviso não acorda a Viv"
        viv.wake("button")
        await until(lambda: viv.state == State.LISTENING and connect.sessions)
        assert connect.session.sent_text == [], "o aviso de quando dormia não é entregue depois"
        assert viv.mention("mensagem nova de Bia") is True
        await until(lambda: connect.session.sent_text)
        assert connect.session.sent_text == ["[Aviso do sistema] mensagem nova de Bia"]
    await run_viv(viv, body)


def test_main_notifies_on_screen_always_and_by_voice_only_when_awake(tmp_path, monkeypatch, events):
    import main
    monkeypatch.chdir(tmp_path)
    cfg = {"settings": {"path": str(tmp_path / "c.json")}, "memory": {"path": str(tmp_path / "m.json")},
           "reminders": {"path": str(tmp_path / "j.json")}, "audit": {"path": str(tmp_path / "a.jsonl")},
           "wake": {"name_enabled": False}, "server": {"port": 8765}}
    parts = main.build(cfg, connect=lambda config: None, audio=FakeAudio())
    spoken = []
    monkeypatch.setattr(parts.viv, "mention", lambda text: spoken.append(text) or True)
    parts.gowa.on_message("5527999990001@s.whatsapp.net", "Maria Silva", "foto")
    parts.gowa.on_message("5527999990001@s.whatsapp.net", "Maria Silva", "texto")
    cards = [text for channel, text, _ in events if channel == "card"]
    assert cards == ["WhatsApp: Maria Silva"], "mensagens seguidas da mesma conversa: um aviso só"
    assert len(spoken) == 1 and "(foto) de Maria Silva" in spoken[0] and "sem inventar o conteúdo" in spoken[0]
    parts.settings.set("whatsapp.avisar_novas", False)
    parts.gowa.on_message("5527999990002@s.whatsapp.net", "Carlos", "texto")
    assert len([1 for channel, _, _ in events if channel == "card"]) == 1


def test_welcome_lists_pending_whatsapp_conversations(tmp_path):
    from viv import briefing
    from viv.settings import Settings

    class NoJobs:
        def pending(self):
            return []

    class NoErrors:
        def recent(self, *a, **k):
            return []
    pending = whatsapp.prepare(whatsapp.clean_chats([
        {"name": "Maria Silva", "unread": 2, "last": "Me liga", "novas": [{"texto": "Me liga"}]},
        {"name": "Família", "group": True, "unread": 1, "last": "Tio Zé: foto", "novas": [{"autor": "Tio Zé", "texto": "foto"}]}]),
        People(str(tmp_path / "p.json")))
    data = briefing.collect(Settings(str(tmp_path / "c.json"), {}), NoJobs(), NoErrors(), whatsapp=pending)
    assert "WhatsApp pendente | Maria Silva (2), Família (1)" in briefing.panel(data)
    prompt = briefing.prompt(data)
    assert "esperando resposta" in prompt and "Tio Zé: “foto”" in prompt and "em grupo, diga quem do grupo escreveu" in prompt
    empty = briefing.collect(Settings(str(tmp_path / "c.json"), {}), NoJobs(), NoErrors(), whatsapp=[])
    assert "nenhuma conversa esperando resposta" in briefing.prompt(empty)
    assert "WhatsApp" not in briefing.prompt(briefing.collect(Settings(str(tmp_path / "c.json"), {}), NoJobs(), NoErrors()))


def test_clicking_a_conversation_in_the_hud_opens_it(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from server import create_app
    from tests.test_server import FakeAudio as ServerAudio, FakeGate as ServerGate, FakeSpeaker, FakeViv
    calls = []
    monkeypatch.setattr(registry, "call", lambda name, args, ctx: calls.append((name, args, ctx)) or "aberta")
    gate = ServerGate()
    gate.ctx = "contexto"
    client = TestClient(create_app(FakeViv(), gate, ServerAudio(), {"server": {"port": 8765}, "live": {}}, FakeSpeaker()))
    origin = {"Origin": "http://127.0.0.1:8765"}
    assert client.post("/api/whatsapp/abrir", json={"contato": "Maria  Silva"}, headers=origin).status_code == 200
    assert calls == [("whatsapp_abrir", {"contato": "Maria Silva"}, "contexto")]
    assert client.post("/api/whatsapp/abrir", json={"contato": "Maria"}).status_code == 403, "outra página não abre conversas"
    assert client.post("/api/whatsapp/abrir", json={"contato": " "}, headers=origin).status_code == 400
