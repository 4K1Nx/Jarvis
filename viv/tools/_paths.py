"""Caminhos ditos pelo usuário viram caminhos reais do Windows.

"Desktop", "Área de Trabalho/notas.txt" ou "~/Downloads" nem sempre ficam em
C:\\Users\\nome\\...: com o OneDrive, a Área de Trabalho e os Documentos mudam de lugar.
Aqui a pasta é perguntada ao próprio Windows.
"""
import os
import unicodedata
from functools import lru_cache
from pathlib import Path

# pasta: (GUID da pasta conhecida do Windows, nome padrão dentro da pasta do usuário)
_KNOWN = {
    "desktop": ("{B4BFCC3A-DB2C-424C-B029-7FE99A87C641}", "Desktop"),
    "documents": ("{FDD39AD0-238F-46AF-ADB4-6C85480369C7}", "Documents"),
    "downloads": ("{374DE290-123F-4565-9164-39C4925E467B}", "Downloads"),
    "pictures": ("{33E28130-4E1E-4676-835A-98395C3BC3BB}", "Pictures"),
    "music": ("{4BD8D571-6D19-48D3-BE97-422220080E43}", "Music"),
    "videos": ("{18989B1D-99B5-455B-841C-AB7C74E4DDFC}", "Videos"),
}
_ALIASES = {
    "desktop": "desktop", "area de trabalho": "desktop",
    "documents": "documents", "documentos": "documents", "meus documentos": "documents",
    "downloads": "downloads", "transferencias": "downloads",
    "pictures": "pictures", "imagens": "pictures", "fotos": "pictures",
    "music": "music", "musicas": "music", "musica": "music",
    "videos": "videos",
}


def _fold(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.casefold().strip())
    return "".join(c for c in text if not unicodedata.combining(c))


@lru_cache(maxsize=None)
def known_folder(key: str) -> Path:
    """Pasta pessoal real (desktop, documents, downloads, pictures, music, videos)."""
    guid, default = _KNOWN[key]
    if os.name == "nt":
        try:
            import ctypes
            from ctypes import wintypes

            class GUID(ctypes.Structure):
                _fields_ = [("a", wintypes.DWORD), ("b", wintypes.WORD), ("c", wintypes.WORD), ("d", ctypes.c_ubyte * 8)]
            folder_id = GUID()
            ctypes.windll.ole32.CLSIDFromString(guid, ctypes.byref(folder_id))
            found = ctypes.c_wchar_p()
            if ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(folder_id), 0, None, ctypes.byref(found)) == 0:
                path = found.value
                ctypes.windll.ole32.CoTaskMemFree(found)
                if path:
                    return Path(path)
        except Exception:
            pass                       # cai para a pasta padrão
    return Path.home() / default


def resolve(path) -> Path:
    """Caminho absoluto para o que o usuário chamou de `path`.

    Um caminho que existe como foi escrito é respeitado. Senão, um nome de pasta pessoal no
    começo ("Desktop/x", "~/Área de Trabalho/x") é trocado pela pasta real, e caminhos
    relativos partem da pasta do usuário.
    """
    text = os.path.expandvars(os.path.expanduser(str(path).strip().strip('"')))
    target = Path(text)
    if target.is_absolute() and target.exists():
        return target
    home = Path.home()
    try:
        parts = target.relative_to(home).parts if target.is_absolute() else target.parts
    except ValueError:
        return target                  # absoluto fora da pasta do usuário: fica como está
    key = _ALIASES.get(_fold(parts[0])) if parts else None
    if key:
        return known_folder(key).joinpath(*parts[1:])
    return target if target.is_absolute() else home.joinpath(*parts)


def personal_roots() -> list[Path]:
    return [known_folder(key) for key in ("desktop", "documents", "downloads", "pictures")]
