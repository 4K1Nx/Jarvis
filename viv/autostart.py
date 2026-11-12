"""Abrir a Viv junto com o Windows: um atalho na pasta Inicializar do usuário."""
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def shortcut_path() -> Path:
    return Path(os.environ.get("APPDATA", "")) / r"Microsoft\Windows\Start Menu\Programs\Startup" / "Viv.lnk"


def is_enabled() -> bool:
    return shortcut_path().is_file()


def enable() -> None:
    """Cria o atalho (janela minimizada) que roda `run.bat --briefing`."""
    link = shortcut_path()
    link.parent.mkdir(parents=True, exist_ok=True)
    script = ("$s=(New-Object -ComObject WScript.Shell).CreateShortcut($env:VIV_LNK);"
              "$s.TargetPath=$env:VIV_TARGET;$s.Arguments='--briefing';$s.WorkingDirectory=$env:VIV_DIR;"
              "$s.WindowStyle=7;$s.Description='Viv, assistente pessoal';$s.Save()")
    env = dict(os.environ, VIV_LNK=str(link), VIV_TARGET=str(ROOT / "run.bat"), VIV_DIR=str(ROOT))
    out = subprocess.run(["powershell", "-NoProfile", "-Command", script], env=env, capture_output=True, timeout=30,
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if out.returncode != 0 or not link.is_file():
        raise RuntimeError("não foi possível criar o atalho de inicialização")


def disable() -> None:
    shortcut_path().unlink(missing_ok=True)


def apply(enabled: bool) -> None:
    enable() if enabled else disable()
