"""Ferramenta para a Viv exibir conteúdo na HUD."""
from viv.bus import BUS
from viv.tools.registry import tool


@tool("hud_mostrar", "Mostrar um cartão na tela com texto, lista ou tabela. Use para listas, tabelas e "
      "informações que ficam melhores escritas do que faladas.",
      {"titulo": {"type": "string"},
       "conteudo": {"type": "string", "description": "texto; lista com um item por linha; tabela com colunas separadas por |"},
       "tipo": {"type": "string", "description": "texto | lista | tabela", "required": False}}, card=False)
def mostrar(titulo, conteudo, tipo="texto", ctx=None):
    if tipo not in ("texto", "lista", "tabela"):
        tipo = "texto"
    BUS.emit("card", titulo, kind="content", body=conteudo, format=tipo, ok=True)
    return "exibido na tela"
