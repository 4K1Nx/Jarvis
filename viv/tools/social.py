"""Pessoas que a Viv conhece (apelidos e relações) e quem está falando com ela."""
from viv.bus import BUS
from viv.tools.registry import tool


@tool("pessoa_definir", "Guardar quem é uma pessoa da vida do usuário: o apelido pelo qual você vai chamá-la, a relação "
      "com o usuário e anotações. Use quando o usuário contar quem é alguém ou quando você perceber a relação. Campos "
      "vazios mantêm o que já estava guardado.",
      {"contato": {"type": "string", "description": "nome exatamente como está salvo no WhatsApp"},
       "apelido": {"type": "string", "description": "como você chama a pessoa, ex.: Mãe, o chefe", "required": False},
       "relacao": {"type": "string", "description": "relação com o usuário, ex.: mãe, colega de trabalho", "required": False},
       "notas": {"type": "string", "description": "o que vale lembrar sobre ela", "required": False}}, title="Pessoa")
def pessoa_definir(contato, apelido="", relacao="", notas="", ctx=None):
    item = ctx.people.define(contato, apelido, relacao, notas)
    return f"guardado: {item.get('apelido') or item['contato']} (contato “{item['contato']}”)"


@tool("pessoa_listar", "Mostrar as pessoas que você conhece, com apelido, relação e anotações.", {}, card=False,
      title="Pessoas", private=True)
def pessoa_listar(ctx=None):
    people = ctx.people.all()
    rows = "\n".join(f"{p.get('apelido') or '—'} | {p['contato']} | {p.get('relacao') or '—'} | {p.get('notas') or ''}" for p in people)
    BUS.emit("card", "Pessoas", kind="content", format="tabela", ok=True,
             body="Apelido | Contato | Relação | Anotações\n" + rows if people else "Ainda não conheço ninguém. Conte quem é quem.")
    return "; ".join(f"{p.get('apelido') or p['contato']} ({p.get('relacao') or 'sem relação anotada'})" for p in people) or "ninguém guardado"


@tool("pessoa_esquecer", "Esquecer o apelido e as anotações de uma pessoa.", {"pessoa": {"type": "string"}}, title="Pessoa")
def pessoa_esquecer(pessoa, ctx=None):
    return "esquecida" if ctx.people.forget(pessoa) else "não conheço ninguém com esse nome"


@tool("voz_quem_fala", "Dizer quem está falando agora, pelo reconhecimento de voz.", {}, card=False, title="Quem fala")
def voz_quem_fala(ctx=None):
    speaker = ctx.speaker
    if speaker is None or not speaker.enrolled:
        return "não há cadastro de voz; não sei quem fala"
    who = speaker.who()
    if not who["heard"]:
        return "ainda não ouvi fala suficiente para reconhecer a voz"
    if not who["known"]:
        return "uma voz que não está cadastrada"
    answer = f"{who['name']}" + (" (o dono)" if who["owner"] else " (voz cadastrada, não é o dono)")
    present = speaker.present()
    return answer + (f". Na conversa agora: {', '.join(present)}" if len(present) > 1 else "")


def _confirm_enroll(args: dict) -> str:
    name = " ".join(str(args.get("nome", "")).split())
    if not name:
        raise ValueError("diga o nome da pessoa")
    return f"Cadastrar a voz de {name}? Ela passa a ser reconhecida pelo nome; só a sua voz continua confirmando ações."


@tool("voz_cadastrar", "Cadastrar a voz de outra pessoa (família, amigos, colegas) para você reconhecê-la pelo nome. Depois de "
      "confirmado, peça para a pessoa falar naturalmente por uns 15 segundos (contar o que fez hoje, por exemplo) e "
      "converse com ela: o cadastro termina sozinho e você é avisada. O dono não deve falar durante o cadastro. A pessoa "
      "é reconhecida, mas não confirma ações. Exige confirmação do dono.",
      {"nome": {"type": "string", "description": "como a pessoa se chama"}},
      dangerous=True, card=False, title="Cadastro de voz", confirm=_confirm_enroll)
def voz_cadastrar(nome, ctx=None):
    if ctx is None or ctx.speaker is None:
        raise ValueError("o reconhecimento de voz está desligado")
    ctx.speaker.begin_enrollment(nome)
    return (f"cadastro de {nome} iniciado: peça para a pessoa falar naturalmente por uns 15 segundos e faça perguntas "
            "simples para ela continuar falando. Você será avisada quando terminar. Para desistir, use voz_cancelar_cadastro.")


@tool("voz_cancelar_cadastro", "Cancelar o cadastro de voz que está em andamento.", {}, title="Cadastro de voz")
def voz_cancelar_cadastro(ctx=None):
    return "cadastro cancelado" if ctx.speaker is not None and ctx.speaker.cancel_enrollment() else "não havia cadastro em andamento"


@tool("voz_pessoas", "Listar as vozes cadastradas e quem está na conversa agora.", {}, title="Vozes")
def voz_pessoas(ctx=None):
    speaker = ctx.speaker
    if speaker is None or not speaker.enrolled:
        return "não há cadastro de voz"
    others = ", ".join(speaker.people) or "nenhuma"
    present = ", ".join(speaker.present()) or "ninguém falou ainda"
    return f"dono: {speaker.owner or 'cadastrado'}. Outras vozes cadastradas: {others}. Na conversa agora: {present}"


@tool("voz_remover", "Apagar o cadastro de voz de uma pessoa (não o do dono). Exige confirmação.",
      {"nome": {"type": "string"}}, dangerous=True, title="Removendo voz",
      confirm=lambda args: f"Apagar o cadastro de voz de {args.get('nome', '')}?")
def voz_remover(nome, ctx=None):
    if ctx.speaker is None or not ctx.speaker.forget_person(nome):
        return "não há voz cadastrada com esse nome"
    return f"cadastro de voz de {nome} apagado"
