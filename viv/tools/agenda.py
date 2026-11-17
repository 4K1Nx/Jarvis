"""Ações agendadas: fazer algo num horário marcado (viv/schedule.py)."""
import json
import re
import unicodedata
from datetime import datetime, timedelta

from viv.bus import BUS
from viv.tools import registry
from viv.tools.registry import tool

# o que não pode ser agendado: os próprios agendamentos, ajustes de segurança e tudo que escreve ou roda código
BLOCKED = ("acao_", "acoes_", "voz_", "contato_adm", "config_", "modelo_", "consentimento_", "habilidade_", "memory_esquecer",
           "viv_", "desktop_run_command", "perguntar", "chat_")
BLOCKED_MODULES = ("viv.tools.code", "viv.tools.agente", "viv.tools.uninstall")
MAX_AHEAD = timedelta(days=366)


def _fold(text: str) -> str:
    text = unicodedata.normalize("NFKD", str(text).casefold())
    return " ".join("".join(c for c in text if not unicodedata.combining(c)).split())


def parse_when(text: str, now: datetime | None = None) -> datetime:
    """Entende “21:30”, “amanhã 8h”, “18/11 09:00”, “2026-11-18 09:00”, “em 20 minutos”, “daqui a 2 horas”."""
    now = now or datetime.now()
    folded = _fold(text).replace(" as ", " ").replace(" de ", " ")
    relative = re.search(r"(?:em|daqui a?)\s*(\d+(?:[.,]\d+)?)\s*(segundo|minuto|min|hora|h|dia)", folded)
    if relative:
        amount = float(relative.group(1).replace(",", "."))
        unit = relative.group(2)
        seconds = amount * (1 if unit.startswith("seg") else 60 if unit.startswith("min") else 3600 if unit.startswith("h") else 86400)
        return now + timedelta(seconds=seconds)
    clock = re.search(r"(\d{1,2})\s*(?::|h)\s*(\d{2})?(?!\d)", folded)
    if not clock:
        raise ValueError("não entendi o horário; use, por exemplo, “21:30”, “amanhã 08:00”, “18/11 09:00” ou “em 20 minutos”")
    hour, minute = int(clock.group(1)), int(clock.group(2) or 0)
    if hour > 23 or minute > 59:
        raise ValueError("horário inválido")
    rest = folded[:clock.start()] + folded[clock.end():]
    day = None
    iso = re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})", rest)
    brazil = re.search(r"(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?", rest)
    try:
        if iso:
            day = datetime(int(iso.group(1)), int(iso.group(2)), int(iso.group(3)))
        elif brazil:
            year = int(brazil.group(3) or now.year)
            day = datetime(year + 2000 if year < 100 else year, int(brazil.group(2)), int(brazil.group(1)))
            if not brazil.group(3) and day.date() < now.date():
                day = day.replace(year=day.year + 1)
    except ValueError:
        raise ValueError("data inválida") from None
    if day is None:
        day = now + timedelta(days=2 if "depois amanha" in rest else 1 if "amanha" in rest else 0)
    when = day.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if not (iso or brazil) and "amanha" not in rest and "hoje" not in rest and when <= now:
        when += timedelta(days=1)             # “às 7h” dito à noite é amanhã
    return when


def _arguments(raw) -> dict:
    if isinstance(raw, dict):
        return raw
    if not str(raw or "").strip():
        return {}
    try:
        data = json.loads(raw)
    except ValueError:
        raise ValueError("os argumentos precisam ser um objeto JSON, ex.: {\"contato\": \"Ana\", \"mensagem\": \"bom dia\"}") from None
    if not isinstance(data, dict):
        raise ValueError("os argumentos precisam ser um objeto JSON")
    return data


def plan(args: dict, now: datetime | None = None) -> tuple[datetime, str, dict, str]:
    """Valida o pedido e devolve (quando, ferramenta, argumentos, descrição). Levanta erro se não puder agendar."""
    now = now or datetime.now()
    name, wanted = str(args.get("ferramenta") or "").strip(), _arguments(args.get("argumentos"))
    if name not in registry.names():
        raise ValueError(f"não existe a ferramenta {name}; use o nome exato de uma das suas ferramentas")
    if name.startswith(BLOCKED) or registry.module_of(name) in BLOCKED_MODULES:
        raise ValueError(f"{name} não pode ser agendada")
    when = parse_when(str(args.get("quando") or ""), now)
    if when <= now:
        raise ValueError("esse horário já passou")
    if when - now > MAX_AHEAD:
        raise ValueError("só agendo com até um ano de antecedência")
    if name == "whatsapp_enviar":
        from viv.people import People
        contact = People().resolve(str(wanted.get("contato") or "").strip())
        message = str(wanted.get("mensagem") or "").strip()
        if not contact or not message:
            raise ValueError("para agendar uma mensagem, informe o contato e a mensagem")
        wanted = {"contato": contact, "mensagem": message}
        text = f"Enviar WhatsApp para {contact}: “{message[:200]}”"
    else:
        text = str(args.get("descricao") or "").strip() or registry.describe(name, wanted)
    return when, name, wanted, text


def _confirm(args: dict) -> str:
    when, _, _, text = plan(args)
    again = ", todo dia" if args.get("todo_dia") else ""
    return f"Agendar para {when:%d/%m às %H:%M}{again}: {text}"


@tool("acao_agendar", "Agendar uma ação para um horário: você mesma executa a ferramenta indicada quando chegar a hora, "
      "sem perguntar de novo. Serve para mandar uma mensagem de WhatsApp num momento específico (ferramenta "
      "whatsapp_enviar, argumentos contato e mensagem; aqui não precisa de rascunho), abrir um programa, apertar uma "
      "tecla, clicar em algo, desligar o PC e as demais ferramentas. O usuário confirma na tela o que e quando. Para só "
      "avisar algo em voz alta, use reminder_set. A Viv precisa estar aberta no horário.",
      {"ferramenta": {"type": "string", "description": "nome exato da ferramenta a executar"},
       "argumentos": {"type": "string", "description": "argumentos da ferramenta, como objeto JSON em texto"},
       "quando": {"type": "string", "description": "ex.: “21:30”, “amanhã 08:00”, “18/11 09:00”, “em 20 minutos”"},
       "descricao": {"type": "string", "description": "frase curta dizendo o que será feito", "required": False},
       "todo_dia": {"type": "boolean", "description": "repetir todos os dias nesse horário", "required": False}},
      dangerous=True, title="Agendar ação", confirm=_confirm, card=False)
def acao_agendar(ferramenta, argumentos="", quando="", descricao="", todo_dia=False, ctx=None):
    when, name, wanted, text = plan({"ferramenta": ferramenta, "argumentos": argumentos, "quando": quando, "descricao": descricao})
    ctx.schedule.add(when.timestamp(), name, wanted, text, daily=bool(todo_dia))
    again = ", todo dia" if todo_dia else ""
    BUS.emit("card", "Ação agendada", kind="data", body=f"{when:%d/%m às %H:%M}{again}: {text}", ok=True)
    return f"agendado para {when:%d/%m às %H:%M}{again}: {text}. A Viv precisa estar aberta nesse horário"


def _lines(jobs: list[dict]) -> list[str]:
    return [f"{i}. {datetime.fromtimestamp(j['at']):%d/%m %H:%M}{' (todo dia)' if j.get('daily') else ''}: {j['text']}"
            for i, j in enumerate(jobs, 1)]


@tool("acoes_agendadas", "Listar as ações agendadas, numeradas.", {}, card=False)
def acoes_agendadas(ctx=None):
    text = "\n".join(_lines(ctx.schedule.pending()))
    BUS.emit("card", "Ações agendadas", kind="content", body=text or "Nenhuma ação agendada.", format="lista", ok=True)
    return text or "nenhuma ação agendada"


@tool("acao_cancelar", "Cancelar uma ação agendada, pelo número dela em acoes_agendadas.",
      {"numero": {"type": "integer"}}, title="Cancelar ação agendada")
def acao_cancelar(numero, ctx=None):
    job = ctx.schedule.cancel(int(numero))
    if job is None:
        raise ValueError("não há ação agendada com esse número; veja a lista com acoes_agendadas")
    return f"cancelada: {job['text']}"
