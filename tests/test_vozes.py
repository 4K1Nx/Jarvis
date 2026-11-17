"""Mais de uma voz: cadastro de outras pessoas pela conversa e percepção de quem está presente."""
import numpy as np
import pytest

from tests.test_novidades import ANA, LONG, OTHER, OWNER, clip, make_speaker
from viv.bus import BUS
from viv.speaker import ENROLL_SAMPLES, PRESENT
from viv.tools import registry, social
from viv.tools.registry import Context

BIA = np.array([0.0, 0.75, 0.66], dtype=np.float32)        # outra voz desconhecida, diferente de OTHER e de ANA


@pytest.fixture
def events(monkeypatch):
    seen = []
    monkeypatch.setattr(BUS, "emit", lambda channel, text="", **extra: seen.append((channel, text, extra)))
    return seen


def test_presence_counts_known_and_distinct_unknown_voices_and_expires(tmp_path, events):
    spk, clock = make_speaker(tmp_path, [OWNER, ANA, OTHER, BIA])
    spk.enroll_person([clip(1)], "Ana")
    spk.hear(clip(0))
    assert spk.present() == ["Gabriel"]
    spk.hear(clip(1))
    spk.hear(clip(2))
    spk.hear(clip(2))                                        # a mesma voz desconhecida não vira duas pessoas
    spk.hear(clip(3))
    assert spk.present() == ["Gabriel", "Ana", "voz desconhecida 1", "voz desconhecida 2"]
    assert [e[2]["people"] for e in events if e[0] == "presence"][-1] == spk.present()
    clock.now += PRESENT + 1
    spk.hear(clip(0))
    assert spk.present() == ["Gabriel"]                      # quem parou de falar há minutos saiu da conversa


def test_a_noisy_owner_is_not_counted_as_a_stranger(tmp_path, events):
    noisy = np.array([0.7, 0.714, 0.0], dtype=np.float32)   # parecida com o dono, abaixo do limiar de certeza
    spk, _ = make_speaker(tmp_path, [OWNER, noisy])
    spk.hear(clip(0))
    spk.hear(clip(1))
    assert spk.present() == ["Gabriel"]


def test_enrollment_through_the_conversation_ignores_the_owner_and_finishes_alone(tmp_path, events):
    spk, _ = make_speaker(tmp_path, [OWNER, ANA])
    done = []
    spk.on_enrolled = done.append
    spk.begin_enrollment("Ana")
    piece = ENROLL_SAMPLES // 2
    spk.hear(clip(0, piece))                                 # o dono falando no meio: não entra no cadastro
    assert spk.enrolling["samples"] == 0
    spk.hear(clip(1, piece))
    assert done == [] and "Ana" not in spk.people
    spk.hear(clip(1, piece))
    assert done == ["Ana"] and spk.enrolling is None
    assert spk.hear(clip(1)) == {"name": "Ana", "owner": False, "known": True, "heard": True}
    assert any(e[0] == "card" and "Ana" in e[1] for e in events)
    assert spk.forget_person("ana") and "Ana" not in spk.people and not spk.forget_person("Ana")


def test_enrollment_rules(tmp_path, events):
    spk, _ = make_speaker(tmp_path, [OWNER, ANA])
    with pytest.raises(ValueError, match="nome do dono"):
        spk.begin_enrollment("gabriel")
    with pytest.raises(ValueError, match="diga o nome"):
        spk.begin_enrollment("  ")
    spk.begin_enrollment("Ana")
    assert spk.cancel_enrollment() and not spk.cancel_enrollment()
    registry.load_all()
    assert registry.is_dangerous("voz_cadastrar", {}) and registry.is_dangerous("voz_remover", {})
    assert "Ana" in registry.confirm_text("voz_cadastrar", {"nome": "Ana"})


def test_tools_list_voices_and_who_is_present(tmp_path, events):
    spk, _ = make_speaker(tmp_path, [OWNER, ANA])
    spk.enroll_person([clip(1)], "Ana")
    ctx = Context({}, speaker=spk)
    spk.hear(clip(0))
    spk.hear(clip(1))
    assert social.voz_quem_fala(ctx=ctx) == "Ana (voz cadastrada, não é o dono). Na conversa agora: Gabriel, Ana"
    assert social.voz_pessoas(ctx=ctx) == "dono: Gabriel. Outras vozes cadastradas: Ana. Na conversa agora: Gabriel, Ana"
    assert "iniciado" in social.voz_cadastrar("Bia", ctx=ctx) and spk.enrolling["name"] == "Bia"
    assert social.voz_cancelar_cadastro(ctx=ctx) == "cadastro cancelado"
    assert "apagado" in social.voz_remover("Ana", ctx=ctx)
