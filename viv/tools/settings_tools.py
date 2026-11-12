"""A Viv configura a si mesma: ajustes, rotina e relatório de erros."""
import subprocess

from viv.bus import BUS
from viv.errors import ERRORS
from viv.settings import SCHEMA, days_label
from viv.tools.registry import tool

KEYS = "; ".join(f"{key} ({spec[2]})" for key, spec in SCHEMA.items())


def _show(value) -> str:
    return ("sim" if value else "não") if isinstance(value, bool) else (str(value) if value != "" else "—")


@tool("config_ver", "Mostrar na tela todas as configurações da Viv e a rotina do usuário.", {}, card=False)
def config_ver(ctx=None):
    rows = ["Ajuste | Valor"] + [f"{item['label']} | {_show(item['value'])}" for item in ctx.settings.items()]
    rows += [f"Rotina {r['hora']} ({days_label(r['dias'])}) | {r['texto']}" for r in ctx.settings.routine()]
    BUS.emit("card", "Configurações da Viv", kind="content", format="tabela", body="\n".join(rows), ok=True)
    return "; ".join(f"{item['key']}={_show(item['value'])}" for item in ctx.settings.items())


@tool("config_definir", "Alterar uma configuração da Viv. Use quando o usuário disser o nome, a cidade, que usa fones, "
      "pedir para iniciar com o Windows, mudar o tempo até dormir, ligar ou desligar palmas, etc. Ajustes: " + KEYS + ".",
      {"chave": {"type": "string", "description": "uma das chaves listadas"},
       "valor": {"type": "string", "description": "texto, número, ou sim/não"}}, title="Configuração")
def config_definir(chave, valor, ctx=None):
    value = ctx.settings.set(chave, valor)
    return f"{SCHEMA[chave][2]} agora é {_show(value)}"


@tool("rotina_adicionar", "Acrescentar um item à rotina diária do usuário. A Viv avisa em voz alta na hora marcada.",
      {"hora": {"type": "string", "description": "ex.: 7:30"},
       "texto": {"type": "string", "description": "o que acontece nessa hora"},
       "dias": {"type": "string", "description": "todos | uteis | fim de semana | seg, qua, sex", "required": False}},
      title="Rotina")
def rotina_adicionar(hora, texto, dias="todos", ctx=None):
    item = ctx.settings.add_routine(hora, texto, dias)
    return f"rotina: {item['hora']} ({days_label(item['dias'])}) {item['texto']}"


@tool("rotina_remover", "Remover itens da rotina que contêm um trecho do texto.", {"trecho": {"type": "string"}},
      title="Rotina")
def rotina_remover(trecho, ctx=None):
    return f"{ctx.settings.remove_routine(trecho)} item(ns) removido(s) da rotina"


@tool("rotina_listar", "Mostrar a rotina do usuário na tela.", {}, card=False)
def rotina_listar(ctx=None):
    items = ctx.settings.routine()
    rows = ["Hora | Dias | O quê"] + [f"{r['hora']} | {days_label(r['dias'])} | {r['texto']}" for r in items]
    BUS.emit("card", "Rotina", kind="content", format="tabela" if items else "texto",
             body="\n".join(rows) if items else "A rotina está vazia.", ok=True)
    return "; ".join(f"{r['hora']} {r['texto']} ({days_label(r['dias'])})" for r in items) or "rotina vazia"


@tool("viv_erros", "Mostrar o relatório dos erros que a Viv teve (ferramentas que falharam, quedas de conexão). "
      "Use quando perguntarem sobre erros, falhas ou problemas dela.",
      {"horas": {"type": "number", "description": "período em horas; omita para os mais recentes", "required": False}},
      card=False)
def viv_erros(horas=None, ctx=None):
    entries = ERRORS.recent(15, hours=float(horas) if horas else None)
    if not entries:
        BUS.emit("card", "Erros da Viv", kind="content", body="Nenhum erro registrado no período.", ok=True)
        return "nenhum erro registrado"
    rows = ["Quando | Origem | Erro"] + [f"{e['quando'][5:16].replace('T', ' ')} | {e['origem']} | {e['erro'][:140]}"
                                         for e in reversed(entries)]
    BUS.emit("card", f"Erros da Viv ({len(entries)})", kind="content", format="tabela", body="\n".join(rows), ok=True)
    return (f"{len(entries)} erro(s). Mais recente: {entries[-1]['origem']}: {entries[-1]['erro'][:200]}. "
            "Relatório completo na tela e no arquivo data/viv_erros.jsonl.")


@tool("system_eventos_erro", "Mostrar os erros recentes do Windows (log de eventos do sistema e de aplicativos). "
      "Use quando o usuário perguntar o que deu errado no computador.",
      {"horas": {"type": "number", "required": False}}, card=False)
def eventos_erro(horas=24, ctx=None):
    hours = max(1, min(168, int(float(horas))))
    command = ("[Console]::OutputEncoding=[Text.Encoding]::UTF8;"
               f"Get-WinEvent -FilterHashtable @{{LogName='System','Application';Level=1,2;StartTime=(Get-Date).AddHours(-{hours})}} "
               "-MaxEvents 12 -ErrorAction SilentlyContinue | ForEach-Object { "
               "$_.TimeCreated.ToString('dd/MM HH:mm') + ' | ' + $_.ProviderName + ' | ' + "
               "(($_.Message -split \"`n\")[0]) }")
    out = subprocess.run(["powershell", "-NoProfile", "-Command", command], capture_output=True, timeout=40,
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    lines = [line.strip()[:220] for line in out.stdout.decode("utf-8", errors="replace").splitlines() if line.strip()]
    if not lines:
        BUS.emit("card", "Erros do Windows", kind="content", body=f"Nenhum erro nas últimas {hours} horas.", ok=True)
        return f"nenhum erro do Windows nas últimas {hours} horas"
    BUS.emit("card", f"Erros do Windows ({len(lines)})", kind="content", format="tabela",
             body="Quando | Origem | Mensagem\n" + "\n".join(lines), ok=True)
    return f"{len(lines)} erro(s) do Windows nas últimas {hours} horas. Mais recente: {lines[0]}. Lista na tela."
