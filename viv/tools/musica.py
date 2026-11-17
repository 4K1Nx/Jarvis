"""Spotify: tocar, pausar, pular, voltar, saber o que toca e ajustar o volume dele (viv/music.py)."""
import time

from viv import music
from viv.tools.registry import tool

ACTIONS = {"tocar": "tocar_pausar", "pausar": "tocar_pausar", "tocar_pausar": "tocar_pausar", "play": "tocar_pausar",
           "pause": "tocar_pausar", "continuar": "tocar_pausar", "proxima": "proxima", "próxima": "proxima",
           "pular": "proxima", "anterior": "anterior", "voltar": "anterior", "parar": "parar"}


def _describe(song) -> str:
    return f"{song['faixa']}, de {song['artista']}" if song else "nada (pausado)"


@tool("spotify_tocar", "Tocar no Spotify uma música, artista, álbum ou playlist específicos. Quando o usuário pedir "
      "uma música aleatória, “qualquer uma” ou “escolhe você”, ESCOLHA você uma música específica (variando estilos, "
      "pensando no humor, na hora e no que ele costuma ouvir), passe artista e nome em pedido e não pergunte qual. "
      "Para “algo pra relaxar/estudar/treinar”, use tipo playlist com o clima pedido.",
      {"pedido": {"type": "string", "description": "o que tocar, com o artista quando souber (ex.: Tempo Perdido Legião Urbana)"},
       "tipo": {"type": "string", "required": False, "description": "musica (padrão), artista, album ou playlist"},
       "embaralhar": {"type": "boolean", "required": False, "description": "artista/álbum/playlist: começar por uma faixa sorteada"}},
      title="Spotify")
def play(pedido, tipo="musica", embaralhar=False, ctx=None):
    from viv.tools.web import search
    kind = music.KINDS.get(music._plain(tipo or "musica").strip(), "track")
    candidates = music.find(str(pedido), kind, lambda text: search(text, 10))
    if not candidates:
        return f"não achei “{pedido}” no Spotify; confirme o nome (e o artista) com o usuário"
    song = None
    for found in candidates[:3]:
        tracks = [] if kind == "track" else music.tracks_of(kind, found["id"])
        if kind != "track" and not tracks:
            continue
        song = music.play_uri(music.uri_for(kind, found["id"], tracks, bool(embaralhar) or kind == "artist"))
        if kind != "track" or music.matches(song, found["titulo"]):
            return f"tocando {_describe(song)}" + (f" ({found['titulo']})" if kind != "track" else "")
    if not song:
        return f"mandei tocar “{pedido}”, mas o Spotify não confirmou; veja se ele abriu"
    return f"não consegui exatamente “{pedido}” (o Spotify trocou a faixa); tocando {_describe(song)}"


@tool("spotify_controle", "Controlar o Spotify do PC: tocar, pausar, próxima, anterior ou parar. "
      "Abre o Spotify se ele estiver fechado. Para tocar algo específico ou aleatório, use spotify_tocar.",
      {"acao": {"type": "string", "description": "tocar | pausar | proxima | anterior | parar"}}, title="Spotify")
def control(acao, ctx=None):
    action = ACTIONS.get(str(acao).strip().lower())
    if action is None:
        raise ValueError("ação do Spotify desconhecida; use tocar, pausar, proxima, anterior ou parar")
    wanted = str(acao).strip().lower()
    if not music.running():
        music.open_app()
        for _ in range(20):                        # até 10 s para a janela dele existir
            time.sleep(0.5)
            if music.running():
                break
        else:
            return "abri o Spotify, mas ele ainda não respondeu; peça de novo em alguns segundos"
        time.sleep(1.5)
    before = music.now_playing()
    if action == "tocar_pausar" and wanted in ("tocar", "play", "continuar") and before:
        return f"já está tocando: {_describe(before)}"
    if action == "tocar_pausar" and wanted in ("pausar", "pause") and not before:
        return "o Spotify já está pausado"
    music.command(action)
    time.sleep(0.8)                                # o título da janela muda logo depois do comando
    return f"feito. Tocando agora: {_describe(music.now_playing())}"


@tool("spotify_tocando", "Dizer qual música está tocando no Spotify agora.", {}, title="Tocando agora")
def playing(ctx=None):
    if not music.running():
        return "o Spotify está fechado"
    return f"tocando: {_describe(music.now_playing())}"


@tool("spotify_volume", "Definir o volume só do Spotify (0 a 100), sem mexer no volume geral do PC.",
      {"percent": {"type": "integer"}}, title="Volume do Spotify")
def volume(percent, ctx=None):
    return f"volume do Spotify em {music.set_volume(percent)}%"
