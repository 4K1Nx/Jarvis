"""Habilidades ensinadas pelo usuário e autodiagnóstico da Viv."""
import importlib.util
import os
from pathlib import Path

from viv import skills
from viv.bus import BUS
from viv.errors import ERRORS
from viv.tools import code
from viv.tools.registry import tool

LIBRARIES = {"Word": "docx", "PowerPoint": "pptx", "Excel": "openpyxl", "PDF (criar)": "reportlab", "PDF (ler)": "pypdf",
             "Navegador automático": "playwright", "Ativação por nome": "faster_whisper"}


@tool("habilidade_salvar", "Guardar uma habilidade: uma sequência de passos que o usuário quer chamar depois pelo nome "
      "(ex.: “modo trabalho”: abrir o Chrome, abrir o Spotify, volume em 30). Use quando ele disser “quando eu falar X, "
      "faça Y” ou “aprenda a…”. Salvar de novo com o mesmo nome substitui.",
      {"nome": {"type": "string"}, "passos": {"type": "string", "description": "os passos, em ordem, em frases curtas"}},
      title="Habilidade")
def habilidade_salvar(nome, passos, ctx=None):
    return skills.save(ctx.cfg, nome, passos) + "; já vale nesta conversa"


@tool("habilidade_remover", "Apagar uma habilidade guardada.", {"nome": {"type": "string"}}, title="Habilidade")
def habilidade_remover(nome, ctx=None):
    return skills.remove(ctx.cfg, nome)


@tool("habilidade_listar", "Mostrar as habilidades que o usuário ensinou.", {}, card=False, title="Habilidades")
def habilidade_listar(ctx=None):
    saved = list(skills.load(ctx.cfg).values())
    body = "\n".join(f"## {s['nome']}\n{s['passos']}" for s in saved) or "Nenhuma habilidade ainda. Diga: **“Viv, quando eu falar modo trabalho, abra…”**"
    BUS.emit("card", "Habilidades", kind="content", format="texto", body=body, ok=True)
    return "; ".join(f"{s['nome']}: {s['passos']}" for s in saved) or "nenhuma habilidade guardada"


def checks(ctx) -> list[tuple[str, bool, str]]:
    """(item, está ok?, detalhe) para cada coisa de que a Viv depende."""
    cfg = ctx.cfg
    rows = [("Conexão com o Gemini", ctx.client is not None, "" if ctx.client is not None else "chave ausente no .env")]
    voiceprint = Path(cfg.get("speaker_id", {}).get("voiceprint_path", "data/voiceprint.json"))
    rows.append(("Cadastro de voz", voiceprint.exists(), "" if voiceprint.exists() else "rode cadastrar_voz.bat"))
    mail = bool(ctx.settings is not None and ctx.settings.get("email.usuario") and os.environ.get("VIV_EMAIL_SENHA"))
    rows.append(("E-mail", mail, "" if mail else "falta o endereço ou a senha de app"))
    for label, module in LIBRARIES.items():
        found = importlib.util.find_spec(module) is not None
        rows.append((label, found, "" if found else f"pip install {module}"))
    rows += [(label, found, "" if found else "não instalado") for label, found in code.self_check().items()]
    recent = len(ERRORS.recent(500, hours=24))
    rows.append(("Erros nas últimas 24 h", recent == 0, f"{recent} registrado(s); pergunte “quais erros você teve?”" if recent else ""))
    return rows


@tool("viv_diagnostico", "Autodiagnóstico da Viv: confere conexão, cadastro de voz, e-mail, bibliotecas de documentos, "
      "ferramentas de programação e erros recentes, e mostra tudo numa tabela. Use quando perguntarem se está tudo "
      "funcionando com você ou o que falta configurar.", {}, card=False, title="Autodiagnóstico")
def viv_diagnostico(ctx=None):
    rows = checks(ctx)
    table = "Item | Estado | Observação\n" + "\n".join(f"{name} | {'✓ ok' if ok else '✗ atenção'} | {note}" for name, ok, note in rows)
    BUS.emit("card", "Autodiagnóstico da Viv", kind="content", format="tabela", body=table, ok=all(ok for _, ok, _ in rows))
    pending = [f"{name} ({note})" if note else name for name, ok, note in rows if not ok]
    return "tudo em ordem" if not pending else "precisam de atenção: " + "; ".join(pending)
