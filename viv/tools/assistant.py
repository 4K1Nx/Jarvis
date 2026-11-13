"""Memória e lembretes."""
from datetime import datetime

from viv.bus import BUS
from viv.tools.registry import tool


@tool("memory_lembrar", "Guardar um fato duradouro sobre o usuário (preferências, nomes, rotinas).",
      {"fato": {"type": "string"}}, title="Memória")
def lembrar(fato, ctx=None):
    return ctx.memory.remember(fato)


@tool("memory_esquecer", "Apagar da memória os fatos que contêm um trecho.",
      {"trecho": {"type": "string"}}, title="Esquecendo")
def esquecer(trecho, ctx=None):
    return ctx.memory.forget(trecho)


@tool("reminder_set", "Criar um lembrete que a Viv fala em voz alta depois de um prazo em segundos.",
      {"texto": {"type": "string"}, "segundos": {"type": "number"}}, card=False)
def reminder_set(texto, segundos, ctx=None):
    ctx.reminders.schedule_in(float(segundos), texto, to=getattr(ctx, "origin", ""))
    when = datetime.fromtimestamp(datetime.now().timestamp() + float(segundos))
    BUS.emit("card", "Lembrete criado", kind="data", body=f"{when:%d/%m %H:%M}: {texto}", ok=True)
    return f"lembrete criado para {when:%H:%M}; a Viv precisa estar aberta para avisar"


@tool("reminder_list", "Listar os lembretes pendentes.", {}, card=False)
def reminder_list(ctx=None):
    jobs = ctx.reminders.pending()
    text = "\n".join(f"{datetime.fromtimestamp(j['at']):%d/%m %H:%M}: {j['text']}" for j in jobs)
    BUS.emit("card", "Lembretes", kind="content", body=text or "Nenhum lembrete pendente.", format="lista", ok=True)
    return text or "nenhum lembrete pendente"
