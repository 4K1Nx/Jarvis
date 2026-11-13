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
    return f"{who['name']}" + (" (o dono)" if who["owner"] else " (voz cadastrada, não é o dono)")
