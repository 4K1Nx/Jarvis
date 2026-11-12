"""Otimização do PC: diagnóstico (só leitura) e limpeza de temporários, caches e lixeira.

A limpeza só apaga arquivos com mais de 24 horas, para não tirar arquivos em uso de
programas abertos, e ignora o que estiver bloqueado. Ela exige confirmação.
"""
import os
import subprocess
import time
import winreg
from concurrent.futures import ThreadPoolExecutor

from viv.bus import BUS
from viv.tools.registry import tool

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def folder_size(path: str) -> int:
    total = 0
    for root, _, files in os.walk(path, onerror=lambda e: None):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(root, name))
            except OSError:
                pass
    return total


def clean_folder(path: str, min_age_hours: float = 24) -> tuple[int, int]:
    """Apaga arquivos antigos de uma pasta. Devolve (bytes liberados, arquivos apagados)."""
    if not os.path.isdir(path):
        return 0, 0
    cutoff, freed, count = time.time() - min_age_hours * 3600, 0, 0
    for root, dirs, files in os.walk(path, topdown=False, onerror=lambda e: None):
        for name in files:
            full = os.path.join(root, name)
            try:
                if os.path.getmtime(full) > cutoff:
                    continue
                size = os.path.getsize(full)
                os.remove(full)
                freed, count = freed + size, count + 1
            except OSError:
                continue          # em uso ou sem permissão: fica
        for name in dirs:
            try:
                os.rmdir(os.path.join(root, name))   # só remove se ficou vazia
            except OSError:
                pass
    return freed, count


def cleanup_targets() -> list[tuple[str, str]]:
    local = os.environ.get("LOCALAPPDATA", "")
    windir = os.environ.get("SystemRoot", r"C:\Windows")
    return [(label, path) for label, path in [
        ("Temporários do usuário", os.environ.get("TEMP", "")),
        ("Temporários do Windows", os.path.join(windir, "Temp")),
        ("Cache do Chrome", os.path.join(local, r"Google\Chrome\User Data\Default\Cache")),
        ("Cache do Edge", os.path.join(local, r"Microsoft\Edge\User Data\Default\Cache")),
        ("Cache do Brave", os.path.join(local, r"BraveSoftware\Brave-Browser\User Data\Default\Cache")),
        ("Miniaturas do Explorer", os.path.join(local, r"Microsoft\Windows\Explorer")),
        ("Relatórios de erro", os.path.join(local, r"Microsoft\Windows\WER")),
        ("Cache de shaders", os.path.join(local, "D3DSCache")),
    ] if path and os.path.isdir(path)]


def _powershell(command: str) -> str:
    out = subprocess.run(["powershell", "-NoProfile", "-Command", command], capture_output=True, timeout=60,
                         creationflags=NO_WINDOW)
    return out.stdout.decode("utf-8", errors="replace").strip()


def recycle_bin_size() -> int:
    try:
        text = _powershell("(New-Object -ComObject Shell.Application).NameSpace(10).Items() | "
                           "ForEach-Object { $_.ExtendedProperty('Size') } | Measure-Object -Sum | "
                           "Select-Object -ExpandProperty Sum")
        return int(float(text or 0))
    except (ValueError, OSError, subprocess.SubprocessError):
        return 0


def empty_recycle_bin() -> bool:
    try:
        _powershell("Clear-RecycleBin -Force -ErrorAction SilentlyContinue")
        return True
    except (OSError, subprocess.SubprocessError):
        return False


def flush_dns() -> bool:
    try:
        return subprocess.run(["ipconfig", "/flushdns"], capture_output=True, timeout=20,
                              creationflags=NO_WINDOW).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def startup_programs() -> list[str]:
    names = []
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        try:
            with winreg.OpenKey(hive, r"Software\Microsoft\Windows\CurrentVersion\Run") as key:
                for i in range(winreg.QueryInfoKey(key)[1]):
                    names.append(winreg.EnumValue(key, i)[0])
        except OSError:
            pass
    return sorted(set(names), key=str.casefold)


def _mb(size: int) -> str:
    return f"{size / 1e9:.1f} GB" if size >= 1e9 else f"{size / 1e6:.0f} MB"


@tool("system_diagnostico", "Diagnóstico do PC: disco, memória, processos pesados, espaço recuperável em temporários, "
      "caches e lixeira, e programas que iniciam com o Windows. Não altera nada. Use quando pedirem para otimizar, "
      "acelerar ou verificar o computador, antes de sugerir a limpeza.", {}, card=False)
def diagnostico(ctx=None):
    import psutil
    disk = psutil.disk_usage(os.path.abspath(os.sep))
    ram = psutil.virtual_memory()
    procs = sorted(psutil.process_iter(["name", "memory_info"]),
                   key=lambda p: p.info["memory_info"].rss if p.info.get("memory_info") else 0, reverse=True)[:5]
    targets = cleanup_targets()
    with ThreadPoolExecutor(max_workers=8) as pool:      # leitura de disco em paralelo
        bin_future = pool.submit(recycle_bin_size)
        sizes = list(pool.map(folder_size, [path for _, path in targets]))
    junk = [(label, size) for (label, _), size in zip(targets, sizes)]
    junk.append(("Lixeira", bin_future.result()))
    total = sum(size for _, size in junk)
    startup = startup_programs()
    rows = ["Item | Valor",
            f"Disco livre | {_mb(disk.free)} de {_mb(disk.total)} ({100 - disk.percent:.0f}% livre)",
            f"Memória em uso | {ram.percent:.0f}% de {_mb(ram.total)}",
            f"Espaço recuperável | {_mb(total)}"]
    rows += [f"· {label} | {_mb(size)}" for label, size in junk if size > 5e6]
    rows += [f"Processo: {p.info['name']} | {_mb(p.info['memory_info'].rss)}" for p in procs]
    rows.append(f"Iniciam com o Windows | {len(startup)}: {', '.join(startup[:8])}")
    BUS.emit("card", "Diagnóstico do PC", kind="content", format="tabela", body="\n".join(rows), ok=True)
    return (f"Disco com {100 - disk.percent:.0f}% livre ({_mb(disk.free)}). Memória em {ram.percent:.0f}%. "
            f"Dá para recuperar cerca de {_mb(total)} em temporários, caches e lixeira. "
            f"Processos mais pesados: {', '.join(p.info['name'] for p in procs[:3])}. "
            f"{len(startup)} programas iniciam com o Windows. Detalhes na tela. "
            "Para limpar, chame system_limpeza (pede confirmação).")


@tool("system_limpeza", "Limpar o PC: apaga arquivos temporários e caches com mais de um dia, esvazia a lixeira e "
      "limpa o cache de DNS. Exige confirmação do usuário.", {}, dangerous=True, card=False)
def limpeza(ctx=None):
    rows, freed, files = ["Local | Liberado"], 0, 0
    for label, path in cleanup_targets():
        size, count = clean_folder(path)
        freed, files = freed + size, files + count
        if count:
            rows.append(f"{label} | {_mb(size)} ({count} arquivos)")
    bin_size = recycle_bin_size()
    if empty_recycle_bin():
        freed += bin_size
        rows.append(f"Lixeira | {_mb(bin_size)}")
    rows.append(f"Cache de DNS | {'limpo' if flush_dns() else 'não foi possível limpar'}")
    rows.append(f"Total | {_mb(freed)}")
    BUS.emit("card", "Limpeza concluída", kind="content", format="tabela", body="\n".join(rows), ok=True)
    return f"Limpeza concluída: {_mb(freed)} liberados, {files} arquivo(s) temporários apagados, lixeira esvaziada."
