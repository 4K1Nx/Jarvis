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


@tool("tarefas_andamento", "Ver as tarefas que você deixou rodando em segundo plano: em que etapa estão, há quanto "
      "tempo, e o resultado das que terminaram há pouco. Use quando o usuário perguntar como está algo que pediu.",
      {}, card=False)
def tarefas_andamento(ctx=None):
    lines = []
    for task in (ctx.tasks.snapshot() if ctx is not None and ctx.tasks is not None else []):
        if task["status"] == "rodando":
            detail = [task["step"]] if task["step"] else []
            if task["value"] is not None:
                detail.append(f"{round(task['value'] * 100)}%")
            detail.append(f"há {task['seconds']} s")
            lines.append(f"{task['title']} — rodando: " + ", ".join(detail))
        else:
            lines.append(f"{task['title']} — {task['status']}: {task['result'][:200]}")
    return "\n".join(lines) or "nenhuma tarefa em segundo plano"


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
