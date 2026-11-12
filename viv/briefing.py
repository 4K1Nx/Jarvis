"""Boas-vindas ao ligar o computador: junta os dados do dia e pede à Viv um resumo falado."""
import shutil
from datetime import datetime

from viv.settings import days_label

DAYS = ["segunda-feira", "terça-feira", "quarta-feira", "quinta-feira", "sexta-feira", "sábado", "domingo"]


def collect(settings, reminders, errors, now: datetime | None = None, fetch_weather=None, unread_count=None,
            disk_path: str = "C:\\") -> dict:
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
    if "disco_livre_pct" in data:
        rows.append(f"Disco livre | {data['disco_livre_gb']} GB ({data['disco_livre_pct']}%)")
    rows.append(f"Erros nas últimas 24 h | {data.get('erros', 0)}")
    return "\n".join(rows)


def prompt(data: dict) -> str:
    """Texto entregue ao modelo; ele transforma em fala."""
    lines = ["O computador acabou de ser ligado e você iniciou junto com ele.",
             "Dê as boas-vindas ao usuário como uma assistente pessoal atenta: cumprimente conforme a hora"
             + (f", chamando-o de {data['nome']}" if data.get("nome") else "")
             + ", diga a hora e faça um relatório falado, natural e curto (no máximo cinco frases) com o que importa "
               "dos dados abaixo. Não leia listas inteiras nem números demais; o painel na tela tem os detalhes. "
               "Mencione um problema só se houver. Termine oferecendo ajuda.",
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
    if data.get("disco_livre_pct") is not None and data["disco_livre_pct"] < 10:
        lines.append(f"Atenção: o disco está com só {data['disco_livre_pct']}% livre ({data['disco_livre_gb']} GB). Sugira a limpeza.")
    if data.get("erros"):
        lines.append(f"Você registrou {data['erros']} erro(s) nas últimas 24 horas; o mais recente: {data['ultimo_erro']}.")
    return "\n".join(lines)
