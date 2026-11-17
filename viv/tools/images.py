"""Imagens para os slides: de acervo de licença livre (Openverse) ou dos arquivos do usuário.

Só entram licenças que permitem reuso com crédito (CC0, domínio público, CC BY, CC BY-SA), e o crédito
acompanha a imagem até a lista de fontes. Uma imagem que falha nunca derruba a criação: o slide sai sem ela.
"""
import io
import re
from pathlib import Path

API = "https://api.openverse.org/v1/images/"
LICENSES = "cc0,pdm,by,by-sa"
LABELS = {"cc0": "CC0", "pdm": "domínio público", "by": "CC BY", "by-sa": "CC BY-SA"}
EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp")
MAX_BYTES, MAX_WIDTH, TIMEOUT = 5 * 1024 * 1024, 1600, 15
AGENT = {"User-Agent": "assistente-pessoal/1.0"}


def _json(query: str) -> dict:
    import httpx
    params = {"q": query, "page_size": 5, "license": LICENSES, "aspect_ratio": "wide", "mature": "false"}
    return httpx.get(API, params=params, timeout=TIMEOUT, headers=AGENT).json()


def _bytes(url: str) -> bytes:
    import httpx
    with httpx.stream("GET", url, timeout=TIMEOUT, follow_redirects=True, headers=AGENT) as reply:
        reply.raise_for_status()
        data = b""
        for chunk in reply.iter_bytes():
            data += chunk
            if len(data) > MAX_BYTES:
                raise ValueError("imagem grande demais")
        return data


def _save(data: bytes, path: Path) -> None:
    """Confere que é mesmo uma imagem, reduz e grava em JPEG."""
    from PIL import Image
    if len(data) > MAX_BYTES:
        raise ValueError("imagem grande demais")
    image = Image.open(io.BytesIO(data))
    image.load()
    if image.width > MAX_WIDTH:
        image = image.resize((MAX_WIDTH, round(image.height * MAX_WIDTH / image.width)))
    path.parent.mkdir(parents=True, exist_ok=True)
    image.convert("RGB").save(path, "JPEG", quality=85)


def find(query: str, folder: Path, fetch_json=None, fetch_bytes=None) -> dict | None:
    """Procura uma imagem livre para a consulta e a guarda em `folder`. Sem nada aproveitável, None."""
    query = " ".join(str(query or "").split())[:80]
    if not query:
        return None
    try:
        results = (fetch_json or _json)(query).get("results") or []
    except Exception:
        return None
    for item in results:
        license_ = str(item.get("license") or "").casefold()
        if license_ not in LABELS or not str(item.get("url") or "").startswith("https://"):
            continue
        path = Path(folder) / (re.sub(r"[^a-z0-9]+", "-", f"{query}-{item.get('id', '')}".casefold()).strip("-")[:70] + ".jpg")
        try:
            _save((fetch_bytes or _bytes)(item["url"]), path)
        except Exception:
            continue                           # não baixou, não é imagem ou é grande demais: tenta a próxima
        version = str(item.get("license_version") or "").strip()
        return {"path": str(path), "titulo": str(item.get("title") or query)[:120],
                "autor": str(item.get("creator") or "autor não informado")[:80],
                "licenca": f"{LABELS[license_]} {version}".strip(),
                "origem": str(item.get("foreign_landing_url") or item["url"])}
    return None


def local(name: str, paths) -> dict | None:
    """Uma imagem que o usuário indicou entre os arquivos, pelo nome (ou parte dele)."""
    from viv.tools._paths import resolve
    wanted = str(name or "").casefold().strip()
    for raw in paths or []:
        if not str(raw).casefold().endswith(EXTENSIONS):
            continue
        target = resolve(str(raw))
        if target.is_file() and wanted and (wanted in target.name.casefold() or target.stem.casefold() in wanted):
            return {"path": str(target), "titulo": target.name, "autor": "arquivo do usuário", "licenca": "", "origem": str(target)}
    return None


def credit(image: dict) -> str:
    parts = [image["titulo"], image["autor"], image["licenca"], image["origem"]]
    return "Imagem: " + ", ".join(p for p in parts if p)
