"""Baixar e instalar programas pelo winget e pelo Chocolatey, num terminal de administrador.

Buscar procura nas duas fontes ao mesmo tempo. Instalar exige confirmação: o cartão mostra o nome, a versão, a
fonte e o ID exatos do pacote. Nunca adivinha: com mais de um candidato, devolve a lista para o usuário escolher.
A instalação roda num PowerShell elevado ("executar como administrador"): o Windows mostra o pedido do UAC, a
Viv espera terminar e lê o resultado de um log temporário. Demorando, vira tarefa de fundo (viv/tasks.py).
"""
import os
import re
import subprocess
import tempfile
import threading
import time
import unicodedata

from viv import tasks
from viv.bus import BUS
from viv.tools.registry import tool

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
SAFE_ID = re.compile(r"^[\w.+\-]{1,128}$")
OK_CODES = {0, 3010, 1641}                       # 3010/1641: instalado, pede reiniciar
ALREADY = {-1978335189, -1978335135}             # winget: nada a atualizar / pacote já instalado
CACHE_SECONDS = 300
_cache: dict[str, tuple[float, list[dict]]] = {}
_lock = threading.Lock()


def _fold(text) -> str:
    text = unicodedata.normalize("NFKD", str(text or "").casefold())
    return "".join(c for c in text if not unicodedata.combining(c) and c.isalnum())


def _run(cmd: list[str], timeout: int = 90) -> str:
    try:
        out = subprocess.run(cmd, capture_output=True, timeout=timeout, creationflags=NO_WINDOW)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return out.stdout.decode("utf-8", errors="replace")


# ---- busca ---------------------------------------------------------------------------------------
def parse_winget(text: str) -> list[dict]:
    """Tabela do `winget search` (cabeçalho em qualquer idioma) -> pacotes. As colunas saem das posições do
    cabeçalho, a linha logo acima da linha de traços."""
    lines = [line.rsplit("\r", 1)[-1].rstrip() for line in text.splitlines()]
    dash = next((i for i, line in enumerate(lines) if line.startswith("---") and set(line) == {"-"}), None)
    if not dash:
        return []
    starts = [m.start() for m in re.finditer(r"\S+", lines[dash - 1])]
    if len(starts) < 3:
        return []
    found = []
    for line in lines[dash + 1:]:
        if not line.strip() or len(line) <= starts[1]:
            continue
        name = line[:starts[1]].strip()
        rest = line[starts[1]:].split()
        if len(rest) < 2 or not SAFE_ID.match(rest[0]):
            continue
        found.append({"nome": name.rstrip("…").strip(), "id": rest[0], "versao": rest[1], "fonte": "winget"})
    return found


def parse_choco(text: str) -> list[dict]:
    """`choco search --limit-output` -> pacotes ("id|versão" por linha)."""
    found = []
    for line in text.splitlines():
        parts = line.strip().split("|")
        if len(parts) == 2 and SAFE_ID.match(parts[0]):
            found.append({"nome": parts[0], "id": parts[0], "versao": parts[1], "fonte": "chocolatey"})
    return found


def search(query: str) -> list[dict]:
    """Busca nas duas fontes ao mesmo tempo; resultados guardados por alguns minutos (a confirmação e a
    instalação usam a mesma busca)."""
    query = str(query or "").strip()
    if not query:
        raise LookupError("diga o nome do programa")
    key = _fold(query)
    with _lock:
        hit = _cache.get(key)
        if hit and time.monotonic() - hit[0] < CACHE_SECONDS:
            return hit[1]
    results = {}

    def winget():
        results["winget"] = parse_winget(_run(["winget", "search", query, "--source", "winget",
                                               "--accept-source-agreements", "--disable-interactivity"]))

    def choco():
        results["choco"] = parse_choco(_run(["choco", "search", query, "--limit-output"]))
    threads = [threading.Thread(target=winget), threading.Thread(target=choco)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    packages = results.get("winget", []) + results.get("choco", [])
    with _lock:
        _cache[key] = (time.monotonic(), packages)
    return packages


def _exact(package: dict, key: str) -> bool:
    ident = package["id"]
    return key in (_fold(package["nome"]), _fold(ident), _fold(ident.split(".")[-1]))


def resolve(nome: str, fonte: str = "", pacote_id: str = "") -> dict:
    """O pacote a instalar. Exato no nome ou no ID; o winget vem antes do Chocolatey. Ambíguo ou só parecido:
    erro com os candidatos, para o usuário escolher."""
    fonte = _fold(fonte)
    fonte = "chocolatey" if fonte.startswith("choco") else "winget" if fonte.startswith("winget") else ""
    packages = search(pacote_id or nome)
    if fonte:
        packages = [p for p in packages if p["fonte"] == fonte]
    if pacote_id:
        same = [p for p in packages if p["id"].casefold() == pacote_id.strip().casefold()]
        if same:
            return same[0]
        raise LookupError(f"o pacote '{pacote_id}' não foi encontrado{' no ' + fonte if fonte else ''}")
    key = _fold(nome)
    for source in ("winget", "chocolatey"):
        exact = [p for p in packages if p["fonte"] == source and _exact(p, key)]
        if len(exact) == 1:
            return exact[0]
        if len(exact) > 1:
            packages = exact
            break
    if len(packages) == 1:
        return packages[0]
    if not packages:
        raise LookupError(f"'{nome}' não foi encontrado no winget nem no Chocolatey. Confirme o nome com o usuário.")
    listed = "; ".join(f"{p['nome']} ({p['fonte']}: {p['id']})" for p in packages[:8])
    raise LookupError(f"há vários pacotes para '{nome}': {listed}. Pergunte qual instalar e chame de novo com o id e a fonte.")


# ---- instalação como administrador ---------------------------------------------------------------
def command_for(package: dict) -> list[str]:
    ident = package["id"]
    if not SAFE_ID.match(ident):
        raise ValueError("id de pacote inválido")
    if package["fonte"] == "chocolatey":
        return ["choco", "install", ident, "-y", "--no-progress"]
    return ["winget", "install", "--id", ident, "--exact", "--source", "winget", "--silent",
            "--accept-package-agreements", "--accept-source-agreements", "--disable-interactivity"]


def run_as_admin(cmd: list[str], timeout: float = 1800) -> tuple[int, str]:
    """Roda o comando num PowerShell elevado e escondido. Devolve (código de saída, saída)."""
    import ctypes
    from ctypes import wintypes
    log = os.path.join(tempfile.gettempdir(), f"viv_instalar_{os.getpid()}_{int(time.time() * 1000)}.log")
    script = f"& {' '.join(cmd)} *>&1 | Out-File -Encoding utf8 -FilePath '{log}'; exit $LASTEXITCODE"

    class Info(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("fMask", ctypes.c_ulong), ("hwnd", wintypes.HWND),
                    ("lpVerb", wintypes.LPCWSTR), ("lpFile", wintypes.LPCWSTR), ("lpParameters", wintypes.LPCWSTR),
                    ("lpDirectory", wintypes.LPCWSTR), ("nShow", ctypes.c_int), ("hInstApp", wintypes.HINSTANCE),
                    ("lpIDList", ctypes.c_void_p), ("lpClass", wintypes.LPCWSTR), ("hkeyClass", wintypes.HKEY),
                    ("dwHotKey", wintypes.DWORD), ("hIcon", wintypes.HANDLE), ("hProcess", wintypes.HANDLE)]
    info = Info(cbSize=ctypes.sizeof(Info), fMask=0x40, lpVerb="runas", lpFile="powershell.exe",   # NOCLOSEPROCESS
                lpParameters=f'-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -Command "{script}"', nShow=0)
    if not ctypes.windll.shell32.ShellExecuteExW(ctypes.byref(info)):
        if ctypes.GetLastError() == 1223:
            raise PermissionError("o pedido de administrador foi recusado no Windows; nada foi instalado")
        raise OSError(f"não consegui abrir o terminal de administrador (erro {ctypes.GetLastError()})")
    kernel = ctypes.windll.kernel32
    try:
        if kernel.WaitForSingleObject(info.hProcess, int(timeout * 1000)) != 0:
            raise TimeoutError("a instalação passou de 30 minutos; confira na tela")
        code = wintypes.DWORD()
        kernel.GetExitCodeProcess(info.hProcess, ctypes.byref(code))
    finally:
        kernel.CloseHandle(info.hProcess)
    try:
        with open(log, encoding="utf-8-sig", errors="replace") as handle:
            output = handle.read()
        os.remove(log)
    except OSError:
        output = ""
    return ctypes.c_int32(code.value).value, output


def _confirm(args) -> str:
    package = resolve(args.get("nome", ""), args.get("fonte", ""), args.get("id", ""))
    return f"Instalar {package['nome']} {package['versao']} pelo {package['fonte']} ({package['id']}), como administrador"


@tool("programa_buscar", "Procurar um programa para baixar no winget e no Chocolatey ao mesmo tempo. Mostra os pacotes "
      "na tela com nome, ID, versão e fonte.", {"nome": {"type": "string"}}, card=False, title="Buscar programa")
def buscar(nome, ctx=None):
    packages = search(nome)
    rows = [f"{p['nome']} — {p['id']} {p['versao']} ({p['fonte']})" for p in packages[:30]]
    BUS.emit("card", f"Pacotes para “{nome}” ({len(packages)})", kind="content", format="lista",
             body="\n".join(rows) or "Nada encontrado no winget nem no Chocolatey.", ok=bool(packages))
    if not packages:
        return "nada encontrado no winget nem no Chocolatey"
    return f"{len(packages)} pacotes, lista na tela. " + "; ".join(rows[:12])


@tool("programa_instalar", "Baixar e instalar um programa no PC pelo winget ou Chocolatey, num terminal de "
      "administrador (o Windows pede permissão). Procura nas duas fontes; se houver mais de um pacote, pergunte ao "
      "usuário e chame de novo com o id e a fonte. Exige confirmação.",
      {"nome": {"type": "string"},
       "fonte": {"type": "string", "required": False, "description": "winget ou chocolatey (opcional)"},
       "id": {"type": "string", "required": False, "description": "ID exato do pacote, quando já se sabe"}},
      dangerous=True, title="Instalar programa", confirm=_confirm)
def instalar(nome, fonte="", id="", ctx=None):
    package = resolve(nome, fonte, id)
    tasks.note(f"instalando {package['nome']} ({package['fonte']})", None)
    code, output = run_as_admin(command_for(package))
    tail = " ".join(output.split())[-300:]
    label = f"{package['nome']} {package['versao']}"
    if code in ALREADY:
        return f"{label} já estava instalado"
    if code not in OK_CODES:
        raise RuntimeError(f"o {package['fonte']} não conseguiu instalar {label} (código {code}). {tail}")
    return f"{label} instalado pelo {package['fonte']}" + (". Pede reiniciar o PC para concluir" if code in (3010, 1641) else "")
