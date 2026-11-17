"""Ferramentas para a Viv exibir conteúdo e fazer perguntas de escolha na HUD."""
from viv.bus import BUS
from viv.tools.registry import tool

# Perguntas com opções que estão na tela, à espera da resposta: pergunta → opções.
OPEN: dict[str, list[str]] = {}


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


@tool("perguntar", "Fazer ao usuário uma pergunta de escolha: ela aparece num cartão com um botão por opção e ele responde "
      "falando ou clicando. Use para combinar como ele quer um material ou uma tarefa (público, tamanho, formato, "
      "fontes) e sempre que houver poucas opções claras. Uma pergunta por chamada; faça-a também em voz alta, dizendo "
      "qual opção você sugere, e espere a resposta. A resposta por clique chega como aviso do sistema.",
      {"pergunta": {"type": "string", "description": "a pergunta, curta"},
       "opcoes": {"type": "array", "items": {"type": "string"}, "description": "de 2 a 5 opções curtas"},
       "sugestao": {"type": "string", "description": "a opção que você recomenda, igual ao texto dela", "required": False}},
      card=False, title="Pergunta")
def perguntar(pergunta, opcoes, sugestao="", ctx=None):
    question = " ".join(str(pergunta).split())[:200]
    options = list(dict.fromkeys(" ".join(str(o).split())[:60] for o in (opcoes or []) if str(o).strip()))
    if not question or not 2 <= len(options) <= 5:
        raise ValueError("a pergunta precisa de um texto e de 2 a 5 opções diferentes")
    OPEN[question] = options
    BUS.emit("ask", question, options=options, suggestion=sugestao if sugestao in options else "")
    return "pergunta na tela; faça-a também em voz alta, dizendo a sua sugestão, e espere a resposta do usuário"


def answer(pergunta: str, opcao: str) -> bool:
    """O usuário clicou numa opção. Só vale se ela pertence a uma pergunta que está aberta."""
    if opcao not in OPEN.get(pergunta, ()):
        return False
    del OPEN[pergunta]
    return True


def close_questions() -> None:
    """O assunto das perguntas foi resolvido (a criação começou): o cartão sai da tela."""
    OPEN.clear()
    BUS.emit("ask_done")
