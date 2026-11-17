"""Boas-vindas ao ligar o computador: junta os dados do dia e pede à Viv um resumo falado."""
import shutil
from datetime import datetime

from viv.settings import days_label

DAYS = ["segunda-feira", "terça-feira", "quarta-feira", "quinta-feira", "sexta-feira", "sábado", "domingo"]


def collect(settings, reminders, errors, now: datetime | None = None, fetch_weather=None, unread_count=None,
            disk_path: str = "C:\\", whatsapp: list[dict] | None = None) -> dict:
    """Cada parte é opcional: o que falhar fica de fora, sem impedir as boas-vindas."""
    now = now or datetime.now()
    data = {"hora": f"{now:%H:%M}", "dia": f"{DAYS[now.weekday()]}, {now:%d/%m/%Y}",
            "nome": settings.get("usuario.nome"), "cidade": settings.get("usuario.cidade")}
    if data["cidade"] and fetch_weather is not None:
        try:
            from viv.tools.weather import parse_weather
            data["clima"] = parse_weather(*fetch_weather(data["cidade"], settings.get("usuario.estado") or None))
        except Exception:
            pass
    data["rotina"] = [f"{r['hora']} {r['texto']}" for r in settings.routine_for(now.weekday())]
    try:
        data["lembretes"] = [f"{datetime.fromtimestamp(j['at']):%d/%m %H:%M} {j['text']}" for j in reminders.pending()][:8]
    except Exception:
        data["lembretes"] = []
    recent = errors.recent(50, hours=24)
    data["erros"] = len(recent)
    data["ultimo_erro"] = f"{recent[-1]['origem']}: {recent[-1]['erro'][:120]}" if recent else ""
    try:
        usage = shutil.disk_usage(disk_path)
        data["disco_livre_pct"] = round(usage.free / usage.total * 100)
        data["disco_livre_gb"] = round(usage.free / 1e9)
    except OSError:
        pass
    if unread_count is not None:
        try:
            data["emails_nao_lidos"] = unread_count()
        except Exception:
            pass
    if whatsapp is not None:
        data["whatsapp"] = whatsapp
    return data


def panel(data: dict) -> str:
    """Tabela para o painel "Resumo do dia" na HUD."""
    rows = ["Item | Agora", f"Data | {data['dia']}, {data['hora']}"]
    clima = data.get("clima")
    if clima:
        rows.append(f"Clima em {clima['city']} | {clima['temp']}°, {clima['desc']} (máx {clima['max']}°, chuva {clima['rain']}%)")
    rows += [f"Rotina | {item}" for item in data.get("rotina", [])]
    rows += [f"Lembrete | {item}" for item in data.get("lembretes", [])]
    if "emails_nao_lidos" in data:
        rows.append(f"E-mails não lidos | {data['emails_nao_lidos']}")
    if "whatsapp" in data:
        rows.append("WhatsApp pendente | " + (", ".join(f"{c['label']} ({c['unread']})" for c in data["whatsapp"]) or "nada"))
    if "disco_livre_pct" in data:
        rows.append(f"Disco livre | {data['disco_livre_gb']} GB ({data['disco_livre_pct']}%)")
    rows.append(f"Erros nas últimas 24 h | {data.get('erros', 0)}")
    return "\n".join(rows)


def tiles(data: dict) -> dict:
    """O mesmo resumo, estruturado para o painel desenhado da HUD: hora, clima, números e listas."""
    numbers = []
    if "emails_nao_lidos" in data:
        numbers.append({"label": "e-mails não lidos", "value": data["emails_nao_lidos"]})
    if "whatsapp" in data:
        numbers.append({"label": "conversas esperando", "value": len(data["whatsapp"])})
    numbers.append({"label": "lembretes", "value": len(data.get("lembretes", []))})
    if "disco_livre_pct" in data:
        numbers.append({"label": "de disco livre", "value": f"{data['disco_livre_pct']}%",
                        "tone": "bad" if data["disco_livre_pct"] < 10 else ""})
    if data.get("erros"):
        numbers.append({"label": "erros em 24 h", "value": data["erros"], "tone": "bad"})
    clima = data.get("clima")
    lists = [{"titulo": "Rotina de hoje", "itens": list(data.get("rotina", []))},
             {"titulo": "Lembretes", "itens": list(data.get("lembretes", []))},
             {"titulo": "WhatsApp esperando resposta",
              "itens": [f"{c['label']} ({c['unread']})" for c in data.get("whatsapp") or []]}]
    return {"hora": data["hora"], "dia": data["dia"], "numeros": numbers[:4], "listas": [g for g in lists if g["itens"]],
            "clima": {k: clima[k] for k in ("city", "temp", "desc", "max", "rain")} if clima else None}


def prompt(data: dict) -> str:
    """Texto entregue ao modelo; ele transforma em fala."""
    lines = [(f"O computador foi ligado às {data['ligado_em']} e você iniciou junto, dormindo. O usuário acabou de te "
              "acordar pela primeira vez: antes de qualquer outra coisa, dê o resumo de tudo."
              if data.get("ligado_em") else "O computador acabou de ser ligado e você iniciou junto com ele."),
             "Dê as boas-vindas ao usuário como uma assistente pessoal atenta: cumprimente conforme a hora"
             + (f", chamando-o de {data['nome']}" if data.get("nome") else "")
             + ", diga a hora e faça um relatório falado, natural e curto (no máximo cinco frases) com o que importa "
               "dos dados abaixo e dos outros avisos desta mensagem (ex.: um projeto que o agente de código terminou "
               "enquanto você dormia). Não leia listas inteiras nem números demais; o painel na tela tem os detalhes. "
               "Mencione um problema só se houver. Se o usuário já tiver pedido algo ao te acordar, faça o resumo em "
               "duas frases e atenda o pedido. Termine oferecendo ajuda.",
             f"Agora: {data['hora']}, {data['dia']}."]
    clima = data.get("clima")
    if clima:
        lines.append(f"Clima em {clima['city']}: {clima['temp']} graus, {clima['desc'].lower()}, máxima de {clima['max']}, "
                     f"{clima['rain']}% de chance de chuva.")
    if data.get("rotina"):
        lines.append("Rotina de hoje: " + "; ".join(data["rotina"]) + ".")
    if data.get("lembretes"):
        lines.append("Lembretes pendentes: " + "; ".join(data["lembretes"]) + ".")
    if "emails_nao_lidos" in data:
        lines.append(f"E-mails não lidos: {data['emails_nao_lidos']}.")
    if data.get("whatsapp"):
        from viv.tools.whatsapp import listing
        lines.append("Conversas do WhatsApp esperando resposta do usuário. Diga quem mandou e, em poucas palavras, sobre o "
                     "quê, uma por uma, pelo apelido; em grupo, diga quem do grupo escreveu. Depois pergunte se ele quer "
                     "responder alguma:\n" + listing(data["whatsapp"]))
    elif "whatsapp" in data:
        lines.append("WhatsApp: nenhuma conversa esperando resposta.")
    if data.get("disco_livre_pct") is not None and data["disco_livre_pct"] < 10:
        lines.append(f"Atenção: o disco está com só {data['disco_livre_pct']}% livre ({data['disco_livre_gb']} GB). Sugira a limpeza.")
    if data.get("erros"):
        lines.append(f"Você registrou {data['erros']} erro(s) nas últimas 24 horas; o mais recente: {data['ultimo_erro']}.")
    return "\n".join(lines)
