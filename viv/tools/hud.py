"""Ferramenta para a Viv exibir conteúdo na HUD."""
from viv.bus import BUS
from viv.tools.registry import tool


@tool("hud_mostrar", "Mostrar um painel na tela com texto formatado. Use para listas, tabelas, passos, código e "
      "informações que ficam melhores escritas do que faladas.",
      {"titulo": {"type": "string"},
       "conteudo": {"type": "string", "description": "texto em markdown simples: ## seções, **negrito**, listas com - ou 1., "
                                                      "- [ ] tarefas, > destaque, `código`, blocos entre ``` e tabelas com | "
                                                      "(segunda linha ---|---). Organize o conteúdo em seções curtas."},
       "tipo": {"type": "string", "description": "texto | lista | tabela", "required": False}}, card=False)
def mostrar(titulo, conteudo, tipo="texto", ctx=None):
    if tipo not in ("texto", "lista", "tabela"):
        tipo = "texto"
    BUS.emit("card", titulo, kind="content", body=conteudo, format=tipo, ok=True)
    return "exibido na tela"
