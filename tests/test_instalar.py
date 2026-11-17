"""Instalar programas: busca no winget e no Chocolatey, escolha exata e execução como administrador."""
import pytest

from viv.tools import instalar

WINGET = ("\r   - \rNome                ID                             Versão     Correspondência\r\n"
          "------------------------------------------------------------------\r\n"
          "Spotify             Spotify.Spotify                1.3.9      ProductCode: spotify\r\n"
          "Toastify            Aleab.Toastify                 1.11.2     Tag: spotify\r\n")
CHOCO = "spotify|1.3.9.2055\nspicetify-cli|2.46.7\n"


@pytest.fixture
def fake(monkeypatch):
    instalar._cache.clear()
    calls = []

    def run(cmd, timeout=90):
        calls.append(cmd)
        return WINGET if cmd[0] == "winget" else CHOCO
    monkeypatch.setattr(instalar, "_run", run)
    return calls


def test_parses_both_sources():
    assert instalar.parse_winget(WINGET) == [
        {"nome": "Spotify", "id": "Spotify.Spotify", "versao": "1.3.9", "fonte": "winget"},
        {"nome": "Toastify", "id": "Aleab.Toastify", "versao": "1.11.2", "fonte": "winget"}]
    assert instalar.parse_choco(CHOCO)[0] == {"nome": "spotify", "id": "spotify", "versao": "1.3.9.2055", "fonte": "chocolatey"}
    assert instalar.parse_winget("Nenhum pacote encontrado.") == []


def test_resolve_prefers_exact_winget_then_choco_and_never_guesses(fake):
    assert instalar.resolve("spotify")["id"] == "Spotify.Spotify"
    assert instalar.resolve("spotify", fonte="choco")["fonte"] == "chocolatey"
    assert instalar.resolve("x", pacote_id="spicetify-cli")["id"] == "spicetify-cli"
    with pytest.raises(LookupError, match="vários pacotes"):
        instalar.resolve("spot")
    assert len(fake) == 6, "três buscas diferentes; a de spotify é reaproveitada"


def test_install_runs_as_admin_only_with_the_exact_package(fake, monkeypatch):
    ran = []
    monkeypatch.setattr(instalar, "run_as_admin", lambda cmd: (ran.append(cmd), (0, "ok"))[1])
    assert instalar._confirm({"nome": "spotify"}).startswith("Instalar Spotify 1.3.9 pelo winget (Spotify.Spotify)")
    assert instalar.instalar("spotify") == "Spotify 1.3.9 instalado pelo winget"
    assert ran[-1][:4] == ["winget", "install", "--id", "Spotify.Spotify"]
    assert "instalado pelo chocolatey" in instalar.instalar("spotify", fonte="chocolatey")
    assert ran[-1] == ["choco", "install", "spotify", "-y", "--no-progress"]
    monkeypatch.setattr(instalar, "run_as_admin", lambda cmd: (-1978335135, ""))
    assert "já estava instalado" in instalar.instalar("spotify")
    monkeypatch.setattr(instalar, "run_as_admin", lambda cmd: (1603, "falhou"))
    with pytest.raises(RuntimeError, match="1603"):
        instalar.instalar("spotify")


def test_unsafe_ids_never_reach_the_terminal():
    with pytest.raises(ValueError):
        instalar.command_for({"id": "x; rm -rf", "fonte": "winget"})
    assert instalar.parse_choco("a&b|1\n") == []
