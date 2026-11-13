"""Apoio a conversas e planos com pessoas próximas: o que lembrar, planejar e retomar.

A Viv organiza; quem decide o que dizer, quando falar e o que fazer é o usuário. Nada
aqui mede afeto, conta respostas curtas ou cria urgência a partir do jeito de alguém
escrever: um lembrete só existe porque o usuário o marcou.

Consentimento é por contato e por finalidade. Sem ele a Viv não lê a conversa de alguém
por conta própria nem guarda nada tirado das mensagens ou dos dados dessa pessoa.
Revogar apaga o que dependia daquela permissão. O arquivo guarda marcas, datas e notas
que o usuário escolheu guardar — nunca o texto das conversas.
"""
import json
import random
import threading
import time
import unicodedata
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable

DAY = 86400
BIRTHDAY_NOTICE = 14            # dias de antecedência para as ideias de presente
EVENT_NOTICE = 30 * 60          # s antes do evento em que as notas aparecem
LONG_SHIFT_HOURS = 10

# finalidade: o que a pessoa precisa saber antes de concordar
PURPOSES = {
    "acompanhamento": {"rotulo": "Acompanhar mensagens a retomar",
                       "fontes": "a conversa do WhatsApp com a pessoa, só para ver se a última mensagem já é sua",
                       "salva": "a marca de que há uma mensagem a retomar; nenhum texto da conversa", "dias": 90, "externo": False},
    "presentes": {"rotulo": "Ideias de presente",
                  "fontes": "os trechos da conversa que você selecionar",
                  "salva": "preferências que ela disse com todas as letras, uma a uma, depois que você aprovar", "dias": 365, "externo": True},
    "agenda": {"rotulo": "Planejar encontros",
               "fontes": "a disponibilidade que ela escolheu compartilhar",
               "salva": "os horários livres que ela informou", "dias": 30, "externo": True},
    "cuidado": {"rotulo": "Sugestões de cuidado",
                "fontes": "plantões e compromissos dela que você cadastrar, e a previsão do tempo",
                "salva": "os compromissos cadastrados", "dias": 180, "externo": True},
    "endereco": {"rotulo": "Usar o endereço dela",
                 "fontes": "o endereço residencial ou de trabalho que ela concordou em informar",
                 "salva": "o endereço", "dias": 365, "externo": True},
}
# tipo de item -> finalidade exigida quando o dado veio da outra pessoa
NEEDS = {"disponibilidade": "agenda", "endereco": "endereco"}


def _fold(text: str) -> str:
    text = unicodedata.normalize("NFKD", str(text).casefold())
    return " ".join("".join(c for c in text if not unicodedata.combining(c)).split())


def parse_when(text: str, now: datetime | None = None) -> datetime:
    """“2026-11-20 19:00”, “20/11/2026 19:00” ou “20/11 19:00” (ano corrente, ou o próximo se já passou)."""
    now, text = now or datetime.now(), " ".join(str(text).replace("T", " ").split())
    for fmt in ("%Y-%m-%d %H:%M", "%d/%m/%Y %H:%M"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            pass
    try:
        when = datetime.strptime(text, "%d/%m %H:%M").replace(year=now.year)
    except ValueError:
        raise ValueError("data inválida; use DD/MM HH:MM ou AAAA-MM-DD HH:MM") from None
    return when if when >= now - timedelta(days=1) else when.replace(year=now.year + 1)


def parse_birthday(text: str) -> tuple[int, int]:
    try:
        day, month = (int(part) for part in str(text).strip().split("/")[:2])
        datetime(2024, month, day)                      # 2024 é bissexto: aceita 29/02
    except (ValueError, TypeError):
        raise ValueError("aniversário inválido; use DD/MM") from None
    return day, month


def in_quiet_hours(now: datetime, start: str, end: str) -> bool:
    """Dentro do horário silencioso? Aceita janelas que atravessam a meia-noite (22:00 a 08:00)."""
    try:
        first, last = (int(t[:2]) * 60 + int(t[3:5]) for t in (start, end))
    except (ValueError, TypeError):
        return False
    minute = now.hour * 60 + now.minute
    if first == last:
        return False
    return first <= minute < last if first < last else (minute >= first or minute < last)


class Relations:
    def __init__(self, path: str = "data/viv_relacoes.json", label: Callable[[str], str] = lambda contact: contact,
                 clock: Callable[[], float] = time.time, pick: Callable[[float, float], float] = random.uniform):
        self.path, self.label, self._clock, self._pick = Path(path), label, clock, pick
        self._lock = threading.RLock()
        self._consent: dict[str, dict] = {}      # contato dobrado -> finalidade -> registro
        self._items: list[dict] = []
        self._meta: dict[str, str] = {}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            self._consent = {k: v for k, v in data.get("consentimentos", {}).items() if isinstance(v, dict)}
            self._items = [i for i in data.get("itens", []) if isinstance(i, dict) and i.get("tipo")]
            self._meta = dict(data.get("meta", {}))
        except (OSError, ValueError, AttributeError):
            pass

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"consentimentos": self._consent, "itens": self._items, "meta": self._meta},
                                  ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(self.path)

    # ---- consentimento ----------------------------------------------------------
    def explain(self, contact: str, purpose: str, days: int | None = None) -> str:
        """O que será usado, o que fica salvo, por quanto tempo e se sai do computador."""
        p = self._purpose(purpose)
        return (f"{p['rotulo']} — {self.label(contact)}. Usa: {p['fontes']}. Salva: {p['salva']}. "
                f"Por {int(days or p['dias'])} dias. "
                + ("Os trechos passam pelo Gemini para a Viv entender." if p["externo"] else "Nada sai do computador."))

    @staticmethod
    def _purpose(purpose: str) -> dict:
        if purpose not in PURPOSES:
            raise ValueError(f"finalidade desconhecida: {purpose}. Use: {', '.join(PURPOSES)}")
        return PURPOSES[purpose]

    def grant(self, contact: str, purpose: str, person_agreed: bool, days: int | None = None) -> dict:
        p = self._purpose(purpose)
        contact = " ".join(str(contact).split())
        if not contact:
            raise ValueError("informe o contato")
        if person_agreed is not True:
            raise PermissionError("só ative depois que a própria pessoa concordar com este uso dos dados dela")
        record = {"contato": contact, "finalidade": purpose, "quando": self._clock(),
                  "dias": max(1, min(730, int(days or p["dias"]))), "externo": p["externo"]}
        with self._lock:
            self._consent.setdefault(_fold(contact), {})[purpose] = record
            self._save()
        return dict(record)

    def allowed(self, contact: str, purpose: str) -> bool:
        """Há consentimento válido? Um consentimento vencido é revogado na hora."""
        with self._lock:
            record = self._consent.get(_fold(contact), {}).get(purpose)
            if record is None:
                return False
            if self._clock() > record["quando"] + record["dias"] * DAY:
                self.revoke(contact, purpose)
                return False
            return True

    def revoke(self, contact: str, purpose: str | None = None) -> int:
        """Revoga uma finalidade (ou todas) e apaga o que dependia dela. Devolve quantos dados saíram."""
        key = _fold(contact)
        with self._lock:
            granted = self._consent.get(key, {})
            purposes = [purpose] if purpose else list(granted)
            for name in purposes:
                granted.pop(name, None)
            if not granted:
                self._consent.pop(key, None)
            kept = [i for i in self._items if not (_fold(i.get("contato", "")) == key and i.get("finalidade") in purposes)]
            removed, self._items = len(self._items) - len(kept), kept
            self._save()
        return removed

    def consents(self, contact: str | None = None) -> list[dict]:
        with self._lock:
            records = [dict(r) for granted in self._consent.values() for r in granted.values()]
        return [r for r in records if (contact is None or _fold(r["contato"]) == _fold(contact))
                and self.allowed(r["contato"], r["finalidade"])]

    # ---- itens ------------------------------------------------------------------
    def add(self, kind: str, text: str, contact: str = "", purpose: str = "", when: float | None = None, **extra) -> dict:
        """Guarda um item. `purpose` marca que o dado veio da outra pessoa: exige consentimento
        e some junto com ele."""
        text, contact = " ".join(str(text).split())[:300], " ".join(str(contact).split())
        purpose = purpose or NEEDS.get(kind, "")
        if not text:
            raise ValueError("nada para guardar")
        if purpose and not self.allowed(contact, purpose):
            raise PermissionError(f"sem consentimento de {self.label(contact) or 'a pessoa'} para “{self._purpose(purpose)['rotulo']}”. "
                                  "Peça ao usuário para confirmar com ela e registrar com consentimento_registrar")
        item = {"id": uuid.uuid4().hex[:8], "tipo": kind, "texto": text, "contato": contact, "finalidade": purpose,
                "quando": when, "criado": self._clock(), "estado": "pendente", **extra}
        with self._lock:
            self._items.append(item)
            self._save()
        return dict(item)

    def find(self, kind: str | None = None, contact: str | None = None) -> list[dict]:
        with self._lock:
            return [dict(i) for i in self._items if (kind is None or i["tipo"] == kind)
                    and (contact is None or _fold(i.get("contato", "")) == _fold(contact))]

    def remove(self, fragment: str, kind: str | None = None) -> int:
        """Apaga os itens cujo texto, nota ou id contém o trecho."""
        key = _fold(fragment)
        if not key:
            return 0
        with self._lock:
            def hit(item):
                texts = [item["texto"], item["id"], *item.get("notas", [])]
                return (kind is None or item["tipo"] == kind) and any(key in _fold(t) for t in texts)
            kept = [i for i in self._items if not hit(i)]
            removed, self._items = len(self._items) - len(kept), kept
            if removed:
                self._save()
        return removed

    def _edit(self, item_id: str, **changes) -> None:
        with self._lock:
            for item in self._items:
                if item["id"] == item_id:
                    item.update(changes)
            self._save()

    # ---- mensagens a retomar ---------------------------------------------------------
    def follow(self, contact: str, minutes: float = 20, note: str = "") -> dict:
        minutes = max(1.0, min(7 * 24 * 60.0, float(minutes)))
        return self.add("retomar", note or "mensagem a retomar", contact, when=self._clock() + minutes * 60)

    def settle(self, contact: str, action: str, minutes: float = 20) -> int:
        """Encerra (“feito”, “dispensar”) ou adia (“adiar”) os lembretes de retomar de um contato."""
        if action not in ("feito", "dispensar", "adiar"):
            raise ValueError("ação inválida: use feito, adiar ou dispensar")
        open_items = [i for i in self.find("retomar", contact) if i["estado"] in ("pendente", "avisado")]
        for item in open_items:
            if action == "adiar":
                self._edit(item["id"], estado="pendente", quando=self._clock() + max(1.0, float(minutes)) * 60)
            else:
                self._edit(item["id"], estado="feito" if action == "feito" else "dispensado")
        return len(open_items)

    # ---- gestos ocasionais -----------------------------------------------------------
    def gesture(self, contact: str, min_weeks: float = 6, max_weeks: float = 8, paused: bool = False) -> dict:
        low = max(1.0, float(min_weeks))
        high = max(low, float(max_weeks))
        with self._lock:
            self._items = [i for i in self._items if not (i["tipo"] == "gesto" and _fold(i["contato"]) == _fold(contact))]
        return self.add("gesto", "gesto ocasional", contact, when=self._clock() + self._pick(low, high) * 7 * DAY,
                        min=low, max=high, pausado=bool(paused))

    def _idea(self, contact: str) -> str:
        ideas = [i["texto"] for i in self.find("presente", contact)] + [i["texto"] for i in self.find("lugar")]
        return ideas[int(self._clock()) % len(ideas)] if ideas else "um bilhete, uma flor ou um plano surpresa"

    # ---- o que está na hora de mostrar ----------------------------------------------------
    def due(self, now: datetime | None = None, quiet: bool = False, answered: Callable[[str], bool] | None = None,
            raining: Callable[[], bool] | None = None, review: bool = False, summary: bool = False,
            weekday: int = 0) -> list[tuple[str, str]]:
        """Avisos privados que venceram, como (título, texto). No horário silencioso nada aparece:
        tudo espera a janela acabar. `answered(contato)` só é consultado com consentimento."""
        now = now or datetime.fromtimestamp(self._clock())
        if quiet:
            return []
        ts, out = now.timestamp(), []
        for item in self.find():
            kind, contact, who = item["tipo"], item["contato"], self.label(item["contato"])
            if kind == "retomar" and item["estado"] == "pendente" and item["quando"] <= ts:
                if answered is not None and self.allowed(contact, "acompanhamento") and self._safe(answered, contact):
                    self._edit(item["id"], estado="feito")          # você já respondeu: o lembrete se encerra
                    continue
                self._edit(item["id"], estado="avisado")
                out.append(("Mensagem para retomar", f"Você marcou uma mensagem para retomar com {who}. "
                            "Diga “Viv, vamos responder”, “adiar” ou “dispensar”."))
            elif kind == "data":
                birthday = datetime(now.year, item["mes"], min(item["dia"], 28 if item["mes"] == 2 else 31))
                if birthday.date() < now.date():
                    birthday = birthday.replace(year=now.year + 1)
                left = (birthday.date() - now.date()).days
                if left <= BIRTHDAY_NOTICE and item.get("avisado") != birthday.year:
                    self._edit(item["id"], avisado=birthday.year)
                    ideas = [i["texto"] for i in self.find("presente", contact)][:3]
                    listing = "Ideias guardadas: " + "; ".join(ideas) + "." if ideas else "Ainda não há ideias de presente guardadas."
                    out.append(("Aniversário chegando", f"O aniversário de {who} é em {left} dia(s), {birthday:%d/%m}. {listing}"))
            elif kind == "evento" and item["estado"] == "pendente" and item["quando"] - EVENT_NOTICE <= ts:
                self._edit(item["id"], estado="avisado")
                if item["quando"] + 3600 < ts:
                    continue                                        # evento que passou com a Viv fechada
                notes = item.get("notas") or []
                out.append((f"Daqui a pouco: {item['texto']}", "Suas notas: " + "; ".join(notes) + "." if notes
                            else "Sem notas guardadas para este evento."))
                care = item.get("plantao") and contact and self.allowed(contact, "cuidado")
                rain = care and raining is not None and self._safe(raining)
                if care and (rain or float(item.get("horas") or 0) >= LONG_SHIFT_HOURS):
                    out.append(("Sugestão de cuidado", f"{who} tem {item['texto']}" + (" e está chovendo" if rain else "")
                                + ". Quer oferecer comida ou perguntar se ela precisa de algo? Antes de qualquer pedido, "
                                "eu confirmo com você o local, o horário e o valor."))
            elif kind == "gesto" and not item.get("pausado") and item["quando"] <= ts:
                self._edit(item["id"], quando=ts + self._pick(item["min"], item["max"]) * 7 * DAY)
                out.append(("Um gesto, se você quiser", f"Faz um tempo desde o último gesto para {who}. Uma ideia: "
                            f"{self._idea(contact)}. Você decide; dá para adiar, dispensar ou pausar."))
        week = f"{now.isocalendar().year}-S{now.isocalendar().week}"
        if now.weekday() == weekday and now.hour >= 9:
            if review and self._meta.get("revisao") != week:
                self._mark_week("revisao", week)
                out.append(("Revisão semanal de encontros", self.dates_overview()))
            if summary and self._meta.get("resumo") != week:
                self._mark_week("resumo", week)
                out.append(("Resumo da semana", self.summary(now)))
        return out

    @staticmethod
    def _safe(check: Callable, *args) -> bool:
        try:
            return bool(check(*args))
        except Exception:
            return False                    # sem WhatsApp ou sem clima, o lembrete segue o caminho comum

    def _mark_week(self, key: str, week: str) -> None:
        with self._lock:
            self._meta[key] = week
            self._save()

    # ---- visões ---------------------------------------------------------------------------
    def dates_overview(self, contact: str | None = None) -> str:
        """O que há para planejar um encontro: só a disponibilidade que cada pessoa compartilhou e a lista de lugares."""
        shared = [i for i in self.find("disponibilidade", contact) if self.allowed(i["contato"], "agenda")]
        places = [i["texto"] for i in self.find("lugar")]
        lines = ["## Disponibilidade compartilhada"]
        lines += [f"- {self.label(i['contato'])}: {i['texto']}" for i in shared] or ["- Ninguém compartilhou disponibilidade ainda."]
        lines += ["## Lugares da lista"] + ([f"- {p}" for p in places] or ["- Lista vazia. Diga “Viv, guarda este lugar”."])
        return "\n".join(lines)

    def summary(self, now: datetime | None = None) -> str:
        """Resumo para organizar as ações do usuário. Não tem métricas sobre ninguém."""
        now = now or datetime.fromtimestamp(self._clock())
        ts = now.timestamp()
        follow = [i for i in self.find("retomar") if i["estado"] in ("pendente", "avisado")]
        plans = [i for i in self.find("plano") if i["estado"] == "pendente"]
        events = sorted((i for i in self.find("evento") if ts <= i["quando"] <= ts + 7 * DAY), key=lambda i: i["quando"])
        dates = []
        for item in self.find("data"):
            day = datetime(now.year, item["mes"], min(item["dia"], 28 if item["mes"] == 2 else 31))
            if day.date() < now.date():
                day = day.replace(year=now.year + 1)
            if (day.date() - now.date()).days <= 30:
                dates.append((day, f"- {day:%d/%m}: aniversário de {self.label(item['contato'])}"))
        gestures = [i for i in self.find("gesto") if not i.get("pausado") and i["quando"] <= ts + 7 * DAY]
        sections = [
            ("Mensagens para retomar", [f"- {self.label(i['contato'])}" + (f": {i['texto']}" if i["texto"] != "mensagem a retomar" else "") for i in follow]),
            ("Planos a confirmar", [f"- {i['texto']}" + (f" ({self.label(i['contato'])})" if i["contato"] else "") for i in plans]),
            ("Datas próximas", [line for _, line in sorted(dates)]),
            ("Eventos da semana", [f"- {datetime.fromtimestamp(i['quando']):%d/%m %H:%M}: {i['texto']}" for i in events]),
            ("Gestos em aberto", [f"- {self.label(i['contato'])}" for i in gestures]),
        ]
        lines = [line for title, rows in sections if rows for line in [f"## {title}", *rows]]
        return "\n".join(lines) or "Nada pendente esta semana."

    def everything(self, contact: str) -> str:
        """Tudo o que está guardado sobre um contato, para consultar, corrigir ou apagar."""
        lines = [f"- consentimento: {PURPOSES[r['finalidade']]['rotulo']} (até "
                 f"{datetime.fromtimestamp(r['quando'] + r['dias'] * DAY):%d/%m/%Y})" for r in self.consents(contact)]
        for item in self.find(contact=contact):
            detail = item["texto"] + (f" — notas: {'; '.join(item['notas'])}" if item.get("notas") else "")
            if item["tipo"] == "data":
                detail = f"aniversário {item['dia']:02d}/{item['mes']:02d}"
            lines.append(f"- {item['tipo']}: {detail} [{item['id']}]")
        return "\n".join(lines) or "Nada guardado sobre esta pessoa."


class RelationsClock:
    """Confere de tempos em tempos o que venceu e entrega os avisos. `deliver(título, texto)`."""

    def __init__(self, relations: Relations, settings, deliver: Callable[[str, str], None],
                 answered: Callable[[str], bool] | None = None, raining: Callable[[], bool] | None = None,
                 now: Callable[[], datetime] = datetime.now):
        self.relations, self.settings, self.deliver = relations, settings, deliver
        self.answered, self.raining, self.now = answered, raining, now
        self._stop = threading.Event()

    def tick(self) -> int:
        from viv.settings import DAY_NAMES
        now, get = self.now(), self.settings.get
        day = get("relacoes.dia_semana").strip().casefold()[:3]
        notices = self.relations.due(
            now, quiet=in_quiet_hours(now, get("silencio.inicio"), get("silencio.fim")), answered=self.answered,
            raining=self.raining, review=get("relacoes.revisao_semanal"), summary=get("relacoes.resumo_semanal"),
            weekday=DAY_NAMES.index(day) if day in DAY_NAMES else 0)
        for title, text in notices:
            self.deliver(title, text)
        return len(notices)

    def start(self) -> None:
        def loop():
            while not self._stop.wait(30):
                try:
                    self.tick()
                except Exception:
                    pass                    # um aviso com problema não pode parar os próximos
        threading.Thread(target=loop, daemon=True, name="viv-relacoes").start()

    def stop(self) -> None:
        self._stop.set()
