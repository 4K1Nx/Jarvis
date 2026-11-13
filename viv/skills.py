"""Habilidades: sequências de passos que o usuário ensina à Viv e chama pelo nome.

"Viv, modo trabalho" → ela segue os passos guardados, usando as ferramentas normais (as ações
sensíveis continuam pedindo confirmação). As habilidades entram na instrução de sistema.
"""
import json
import threading
import unicodedata
from pathlib import Path

MAX_SKILLS, MAX_STEPS = 30, 1200
_lock = threading.Lock()


def _key(name: str) -> str:
    text = unicodedata.normalize("NFKD", str(name).casefold().strip())
    return " ".join("".join(c for c in text if not unicodedata.combining(c)).split())


def _path(cfg: dict) -> Path:
    return Path(cfg.get("skills", {}).get("path", "data/viv_habilidades.json"))


def load(cfg: dict) -> dict[str, dict]:
    """{chave: {"nome": ..., "passos": ...}}; arquivo ausente ou corrompido vira vazio."""
    try:
        data = json.loads(_path(cfg).read_text(encoding="utf-8"))
        return {k: v for k, v in data.items() if isinstance(v, dict) and v.get("nome") and v.get("passos")}
    except (OSError, ValueError, AttributeError):
        return {}


def _store(cfg: dict, skills: dict) -> None:
    path = _path(cfg)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(skills, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)


def save(cfg: dict, name: str, steps: str) -> str:
    name, steps = " ".join(str(name).split()), str(steps).strip()
    if not _key(name) or not steps:
        raise ValueError("diga o nome da habilidade e os passos")
    if len(steps) > MAX_STEPS:
        raise ValueError("passos longos demais; resuma em até 1200 caracteres")
    with _lock:
        skills = load(cfg)
        if _key(name) not in skills and len(skills) >= MAX_SKILLS:
            raise ValueError("limite de 30 habilidades atingido; remova alguma antes")
        skills[_key(name)] = {"nome": name, "passos": steps}
        _store(cfg, skills)
    return f"habilidade “{name}” guardada"


def remove(cfg: dict, name: str) -> str:
    with _lock:
        skills = load(cfg)
        if skills.pop(_key(name), None) is None:
            return f"não existe habilidade chamada {name}"
        _store(cfg, skills)
    return f"habilidade “{name}” removida"


def prompt_block(cfg: dict) -> str:
    skills = load(cfg)
    if not skills:
        return ""
    lines = "\n".join(f"- {s['nome']}: {s['passos']}" for s in skills.values())
    return ("Habilidades que o usuário ensinou. Quando ele pedir uma delas pelo nome, siga os passos com as ferramentas, "
            "um de cada vez:\n" + lines)
