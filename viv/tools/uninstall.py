"""Programas instalados e desinstalação pelo winget. Desinstalar sempre exige confirmação,
e o cartão de confirmação mostra o nome exato do programa encontrado."""
import subprocess
import winreg

from viv.bus import BUS
from viv.tools.apps import _fold, _key, find_app
from viv.tools.registry import tool

UNINSTALL = r"Software\Microsoft\Windows\CurrentVersion\Uninstall"


def installed_programs() -> list[dict]:
    names = set()
    for hive, flag in ((winreg.HKEY_LOCAL_MACHINE, winreg.KEY_WOW64_64KEY), (winreg.HKEY_LOCAL_MACHINE, winreg.KEY_WOW64_32KEY),
                       (winreg.HKEY_CURRENT_USER, 0)):
        try:
            with winreg.OpenKey(hive, UNINSTALL, 0, winreg.KEY_READ | flag) as root:
                for i in range(winreg.QueryInfoKey(root)[0]):
                    try:
                        with winreg.OpenKey(root, winreg.EnumKey(root, i)) as key:
                            name = winreg.QueryValueEx(key, "DisplayName")[0].strip()
                            try:
                                if winreg.QueryValueEx(key, "SystemComponent")[0] == 1:
                                    continue
                            except OSError:
                                pass
                            if name:
                                names.add(name)
                    except OSError:
                        continue
        except OSError:
            continue
    return [{"Name": name, "AppID": name} for name in sorted(names, key=_fold)]


def resolve(nome: str) -> str:
    """Nome exato do programa a desinstalar. Nunca adivinha: com mais de um candidato, ou só
    com um nome parecido, devolve erro pedindo o nome completo."""
    wanted = _key(nome)
    programs = installed_programs()
    if not wanted:
        raise LookupError("diga o nome do programa")
    exact = [p["Name"] for p in programs if _key(p["Name"]) == wanted]
    if len(exact) == 1:
        return exact[0]
    candidates = [p["Name"] for p in programs if wanted in _key(p["Name"])]
    if len(candidates) == 1:
        return candidates[0]
    if len(candidates) > 1:
        raise LookupError(f"há mais de um programa com '{nome}': {', '.join(candidates[:8])}. Peça o nome completo ao usuário.")
    match, suggestions = find_app(nome, programs)
    similar = [match["Name"]] if match else suggestions
    hint = f" Parecidos: {', '.join(similar)}. Confirme o nome com o usuário." if similar else ""
    raise LookupError(f"programa '{nome}' não encontrado entre os instalados.{hint}")


@tool("system_programas", "Listar os programas instalados que podem ser desinstalados, com filtro opcional. Mostra na tela.",
      {"filtro": {"type": "string", "required": False}}, card=False)
def programas(filtro=None, ctx=None):
    names = [p["Name"] for p in installed_programs()]
    if filtro:
        names = [n for n in names if _key(filtro) in _key(n)]
    BUS.emit("card", f"Programas instalados ({len(names)})", kind="content", format="lista",
             body="\n".join(names) or "Nenhum programa encontrado.", ok=True)
    return (f"{len(names)} programas, lista na tela. " + ", ".join(names[:40])) if names else "nenhum programa encontrado"


@tool("system_desinstalar", "Desinstalar um programa do computador pelo nome. Irreversível; exige confirmação.",
      {"nome": {"type": "string"}}, dangerous=True, title="Desinstalar",
      confirm=lambda args: f"Desinstalar: {resolve(args.get('nome', ''))}")
def desinstalar(nome, ctx=None):
    exact = resolve(nome)
    out = subprocess.run(["winget", "uninstall", "--name", exact, "--exact", "--silent", "--disable-interactivity",
                          "--accept-source-agreements"], capture_output=True, timeout=900,
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    tail = " ".join(out.stdout.decode("utf-8", errors="replace").split())[-240:]
    if out.returncode != 0:
        raise RuntimeError(f"o winget não conseguiu desinstalar {exact} (código {out.returncode}). {tail}")
    return f"{exact} desinstalado"
