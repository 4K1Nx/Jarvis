"""Configurações do usuário e rotina, editáveis pela HUD e pela própria Viv.

Tudo o que é ajustável mora no SCHEMA. Acrescentar um ajuste novo é acrescentar uma
linha aqui: ele aparece na tela de configurações e a Viv passa a saber alterá-lo.
"""
import json
import re
import threading
import uuid
from pathlib import Path
from typing import Any, Callable

# chave: (tipo, padrão, rótulo, descrição, caminho em config.yaml ou None)
SCHEMA: dict[str, tuple] = {
    "usuario.nome": (str, "", "Seu nome", "Como a Viv chama você.", None),
    "usuario.cidade": (str, "", "Cidade", "Usada no clima e nas boas-vindas.", None),
    "usuario.estado": (str, "", "Estado", "Ajuda a achar a cidade certa.", None),
    "audio.fones": (bool, False, "Uso fones de ouvido", "Com fones, o microfone fica aberto enquanto a Viv fala.", ("audio", "headphones")),
    "audio.sensibilidade_interrupcao": (float, 0.08, "Volume para interromper", "Sem fones: quanto maior, mais alto é preciso falar para interrompê-la (0,03 a 0,3).", ("audio", "barge_in_rms")),
    "conversa.segundos_ate_dormir": (int, 60, "Segundos até dormir", "Silêncio até a Viv dormir (15 a 600).", ("assistant", "idle_seconds")),
    "ativacao.palmas": (bool, True, "Acordar com duas palmas", "", ("wake", "clap_enabled")),
    "ativacao.nome": (bool, True, "Acordar com “Ei, Viv”", "", ("wake", "name_enabled")),
    "inicio.com_windows": (bool, False, "Abrir junto com o Windows", "A Viv inicia quando o computador liga.", None),
    "inicio.boas_vindas": (bool, True, "Boas-vindas ao ligar", "Ao iniciar com o Windows, ela faz um resumo do dia.", None),
    "email.usuario": (str, "", "E-mail", "Endereço da conta. A senha de app fica no arquivo .env (VIV_EMAIL_SENHA).", None),
    "email.servidor": (str, "imap.gmail.com", "Servidor IMAP", "Gmail: imap.gmail.com. Outlook: outlook.office365.com.", None),
}
RANGES = {"audio.sensibilidade_interrupcao": (0.03, 0.3), "conversa.segundos_ate_dormir": (15, 600)}
TRUE = {"sim", "true", "1", "ligado", "ligar", "ativo", "ativar", "on", "verdadeiro", "s"}
FALSE = {"nao", "não", "false", "0", "desligado", "desligar", "inativo", "desativar", "off", "falso", "n"}
DAY_NAMES = ["seg", "ter", "qua", "qui", "sex", "sab", "dom"]
DAY_GROUPS = {"todos": list(range(7)), "todo dia": list(range(7)), "diario": list(range(7)),
              "uteis": [0, 1, 2, 3, 4], "dias uteis": [0, 1, 2, 3, 4], "semana": [0, 1, 2, 3, 4],
              "fim de semana": [5, 6], "fins de semana": [5, 6], "fim_de_semana": [5, 6]}


def _fold(text: str) -> str:
    import unicodedata
    text = unicodedata.normalize("NFKD", str(text).casefold().strip())
    return "".join(c for c in text if not unicodedata.combining(c))


def parse_time(text: str) -> str:
    """Aceita 7, 7h, 7:30, 07h30, 19.45 e devolve HH:MM."""
    match = re.fullmatch(r"\s*(\d{1,2})\s*(?:[:h.]\s*(\d{1,2}))?\s*(?:h|hs|horas|min)?\s*", str(text).lower())
    if not match:
        raise ValueError(f"hora inválida: {text}")
    hour, minute = int(match.group(1)), int(match.group(2) or 0)
    if hour > 23 or minute > 59:
        raise ValueError(f"hora inválida: {text}")
    return f"{hour:02d}:{minute:02d}"


def parse_days(text) -> list[int]:
    if isinstance(text, list):
        days = sorted({int(d) for d in text if 0 <= int(d) <= 6})
        return days or list(range(7))
    key = _fold(text or "todos")
    if key in DAY_GROUPS:
        return DAY_GROUPS[key]
    days = sorted({i for i, name in enumerate(DAY_NAMES) for word in re.findall(r"[a-z]+", key) if word.startswith(name)})
    if not days:
        raise ValueError(f"dias inválidos: {text}. Use todos, uteis, fim de semana ou seg, ter, qua...")
    return days


def days_label(days: list[int]) -> str:
    if days == list(range(7)):
        return "todos os dias"
    if days == [0, 1, 2, 3, 4]:
        return "dias úteis"
    if days == [5, 6]:
        return "fim de semana"
    return ", ".join(["seg", "ter", "qua", "qui", "sex", "sáb", "dom"][d] for d in days)


class Settings:
    def __init__(self, path: str, cfg: dict | None = None):
        self.path = Path(path)
        self._lock = threading.RLock()
        self._listeners: list[Callable[[str, Any], None]] = []
        self._values: dict[str, Any] = {}
        self._routine: list[dict] = []
        self._defaults = {key: spec[1] for key, spec in SCHEMA.items()}
        for key, spec in SCHEMA.items():          # o padrão efetivo vem do config.yaml, quando existe
            if spec[4] and cfg:
                section, name = spec[4]
                if name in cfg.get(section, {}):
                    self._defaults[key] = spec[0](cfg[section][name])
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            self._values = {k: v for k, v in data.get("values", {}).items() if k in SCHEMA}
            self._routine = [r for r in data.get("rotina", []) if isinstance(r, dict) and r.get("hora") and r.get("texto")]
        except (OSError, ValueError, AttributeError):
            pass

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"values": self._values, "rotina": self._routine}, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(self.path)

    # ---- valores ---------------------------------------------------------
    def get(self, key: str) -> Any:
        if key not in SCHEMA:
            raise KeyError(key)
        with self._lock:
            return self._values.get(key, self._defaults[key])

    def set(self, key: str, value: Any) -> Any:
        if key not in SCHEMA:
            raise KeyError(f"ajuste desconhecido: {key}. Ajustes válidos: {', '.join(SCHEMA)}")
        kind = SCHEMA[key][0]
        if kind is bool:
            if not isinstance(value, bool):
                folded = _fold(value)
                if folded not in TRUE | FALSE:
                    raise ValueError(f"{key} aceita sim ou não")
                value = folded in TRUE
        elif kind in (int, float):
            try:
                value = kind(float(str(value).replace(",", ".")))
            except ValueError:
                raise ValueError(f"{key} precisa ser um número") from None
            low, high = RANGES.get(key, (None, None))
            if low is not None and not low <= value <= high:
                raise ValueError(f"{key} precisa estar entre {low} e {high}")
        else:
            value = str(value).strip()[:200]
        with self._lock:
            self._values[key] = value
            self._save()
            listeners = list(self._listeners)
        for listener in listeners:
            listener(key, value)
        return value

    def on_change(self, listener: Callable[[str, Any], None]) -> None:
        self._listeners.append(listener)

    def items(self) -> list[dict]:
        kinds = {bool: "bool", int: "int", float: "float", str: "text"}
        return [{"key": key, "label": spec[2], "description": spec[3], "type": kinds[spec[0]], "value": self.get(key)}
                for key, spec in SCHEMA.items()]

    def overlay(self, cfg: dict) -> dict:
        """Aplica sobre o config.yaml carregado os ajustes que o usuário mudou."""
        with self._lock:
            for key, value in self._values.items():
                target = SCHEMA[key][4]
                if target:
                    cfg.setdefault(target[0], {})[target[1]] = value
        return cfg

    # ---- rotina ----------------------------------------------------------
    def routine(self) -> list[dict]:
        with self._lock:
            return sorted((dict(r) for r in self._routine), key=lambda r: r["hora"])

    def add_routine(self, hora: str, texto: str, dias="todos") -> dict:
        texto = str(texto).strip()
        if not texto:
            raise ValueError("descreva o item da rotina")
        item = {"id": uuid.uuid4().hex[:8], "hora": parse_time(hora), "dias": parse_days(dias), "texto": texto[:200]}
        with self._lock:
            self._routine.append(item)
            self._save()
        return item

    def remove_routine(self, ref: str) -> int:
        """Remove pelo id ou por um trecho do texto. Devolve quantos saíram."""
        key = _fold(ref)
        if not key:
            return 0
        with self._lock:
            kept = [r for r in self._routine if r["id"] != ref and key not in _fold(r["texto"])]
            removed = len(self._routine) - len(kept)
            if removed:
                self._routine = kept
                self._save()
        return removed

    def routine_for(self, weekday: int) -> list[dict]:
        return [r for r in self.routine() if weekday in r["dias"]]
