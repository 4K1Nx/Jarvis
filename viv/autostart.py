"""Abrir a Viv junto com o Windows, dormindo.

Usa a chave Run do registro do usuário (HKCU), não a pasta Inicializar: neste computador os atalhos da
pasta Inicializar deixaram de ser executados, e a chave Run roda logo após o login. O comando usa o
pythonw.exe do ambiente da Viv, então nenhuma janela de CMD aparece; a saída vai para data/inicio.log.
"""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE = "Viv"


def shortcut_path() -> Path:
    """Atalho antigo na pasta Inicializar; é removido ao ativar ou desativar."""
    return Path(os.environ.get("APPDATA", "")) / r"Microsoft\Windows\Start Menu\Programs\Startup" / "Viv.lnk"


def command() -> str:
    python = ROOT / ".venv" / "Scripts" / "pythonw.exe"
    return f'"{python}" -X utf8 "{ROOT / "main.py"}" --briefing'


def _key(write: bool = False):
    import winreg
    access = winreg.KEY_SET_VALUE | winreg.KEY_QUERY_VALUE if write else winreg.KEY_QUERY_VALUE
    return winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, access)


def current() -> str | None:
    import winreg
    try:
        with _key() as key:
            return winreg.QueryValueEx(key, VALUE)[0]
    except OSError:
        return None


def is_enabled() -> bool:
    return current() is not None


def enable() -> None:
    import winreg
    if not (ROOT / ".venv" / "Scripts" / "pythonw.exe").is_file():
        raise RuntimeError("ambiente Python da Viv não encontrado (.venv); veja a instalação no README_VIV.md")
    try:
        with _key(write=True) as key:
            winreg.SetValueEx(key, VALUE, 0, winreg.REG_SZ, command())
    except OSError as exc:
        raise RuntimeError(f"não foi possível registrar a inicialização com o Windows: {exc}") from exc
    shortcut_path().unlink(missing_ok=True)


def disable() -> None:
    import winreg
    try:
        with _key(write=True) as key:
            winreg.DeleteValue(key, VALUE)
    except FileNotFoundError:
        pass
    shortcut_path().unlink(missing_ok=True)


def apply(enabled: bool) -> None:
    enable() if enabled else disable()


def sync(enabled: bool) -> None:
    """Ao abrir a Viv: deixa o registro de acordo com a configuração (migra o atalho antigo e corrige
    o caminho se a pasta da Viv mudou de lugar). Nunca impede a Viv de abrir."""
    try:
        if enabled and (current() != command() or shortcut_path().exists()):
            enable()
        elif not enabled and (is_enabled() or shortcut_path().exists()):
            disable()
    except Exception as exc:
        from viv.errors import ERRORS
        ERRORS.record("inicialização com o Windows", str(exc))
