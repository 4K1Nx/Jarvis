"""Spotify: título da janela, ferramentas e o analisador que faz o avatar dançar."""
import numpy as np
import pytest

from viv import music
from viv.tools import musica


def test_title_of_the_spotify_window_tells_what_is_playing():
    assert music.parse_title("Daft Punk - One More Time") == {"artista": "Daft Punk", "faixa": "One More Time"}
    assert music.parse_title("Legião Urbana - Tempo Perdido - Remaster") == {"artista": "Legião Urbana", "faixa": "Tempo Perdido - Remaster"}
    for paused in ("Spotify Premium", "Spotify Free", "Spotify", "", "Advertisement"):
        assert music.parse_title(paused) is None


def test_bass_lights_the_low_bands_and_silence_turns_them_off():
    t = np.arange(music.FFT) / music.RATE
    peaks = np.full(10, 1e-3)
    bands, bass, level = music.analyze((0.3 * np.sin(2 * np.pi * 60 * t)).astype(np.float32), peaks, 0.05)
    assert len(bands) == 10 and bands[0] > 0.5 and max(bands[5:]) < 0.2 and bass > 0.5 and level > 0
    bands, bass, level = music.analyze(np.zeros(music.FFT, dtype=np.float32), peaks, 0.05)
    assert bands == [0.0] * 10 and bass == 0 and level == 0


def test_controls_go_to_spotify_and_say_what_is_playing(monkeypatch):
    sent, songs = [], [None, {"artista": "A", "faixa": "B"}]
    monkeypatch.setattr(music, "running", lambda: True)
    monkeypatch.setattr(music, "now_playing", lambda: songs[0] if not sent else songs[1])
    monkeypatch.setattr(music, "command", sent.append)
    monkeypatch.setattr(musica.time, "sleep", lambda s: None)
    assert "B, de A" in musica.control("tocar") and sent == ["tocar_pausar"]
    assert musica.control("tocar").startswith("já está tocando") and sent == ["tocar_pausar"]
    assert musica.control("próxima") and sent[-1] == "proxima"
    with pytest.raises(ValueError):
        musica.control("dançar")


def test_visualizer_only_listens_while_spotify_plays_and_the_setting_is_on():
    settings = {"musica.visualizar": True}
    song = {"artista": "A", "faixa": "B"}
    vis = music.Visualizer(type("S", (), {"get": lambda self, key: settings[key]})(), playing=lambda: song)
    assert vis.wanted() == song
    settings["musica.visualizar"] = False
    assert vis.wanted() is None


HITS = {
    "track": [{"title": "Outra Coisa - song and lyrics by Fulano | Spotify", "url": "https://open.spotify.com/track/AAAAAAAAAAAAAAAAAAAAAA"},
              {"title": "Tempo Perdido - Ao Vivo - song and lyrics by Legião Urbana | Spotify", "url": "https://open.spotify.com/track/BBBBBBBBBBBBBBBBBBBBBB"},
              {"title": "Tempo Perdido - song and lyrics by Legião Urbana | Spotify", "url": "https://open.spotify.com/intl-pt/track/CCCCCCCCCCCCCCCCCCCCCC"},
              {"title": "YouTube", "url": "https://youtube.com/watch?v=x"}],
}


def test_find_ranks_the_requested_version_first_and_skips_other_sites():
    found = music.find("Tempo Perdido Legião Urbana", "track", lambda text: HITS["track"])
    assert [f["id"] for f in found] == ["CCCCCCCCCCCCCCCCCCCCCC", "BBBBBBBBBBBBBBBBBBBBBB"], "ao vivo só se pedir; sem relação fica fora"
    assert music.find("nada a ver", "track", lambda text: HITS["track"]) == []
    assert music.matches({"faixa": "Tempo Perdido", "artista": "Legião Urbana"}, found[0]["titulo"])
    assert not music.matches({"faixa": "The Show Must Go On", "artista": "Queen"}, "Bohemian Rhapsody - song and lyrics by Queen")


def test_playlists_start_from_one_of_their_tracks_with_the_rest_queued():
    page = ('<script id="__NEXT_DATA__" type="application/json">{"props":{"trackList":['
            '{"uri":"spotify:track:111111111111111111111A","title":"Um","subtitle":"X","isPlayable":true},'
            '{"uri":"spotify:track:222222222222222222222B","title":"Dois","subtitle":"Y","isPlayable":false}]}}</script>')
    tracks = music.tracks_of("playlist", "P" * 22, get=lambda url: page)
    assert tracks == [{"id": "111111111111111111111A", "faixa": "Um", "artista": "X"}]
    assert music.uri_for("playlist", "P" * 22, tracks) == "spotify:track:111111111111111111111A?context=spotify:playlist:" + "P" * 22
    assert music.uri_for("track", "T" * 22, []) == "spotify:track:" + "T" * 22


def test_play_pauses_first_because_an_open_link_does_not_interrupt(monkeypatch):
    playing = [{"faixa": "Velha", "artista": "A"}]
    sent, opened = [], []
    monkeypatch.setattr(music, "running", lambda: True)
    monkeypatch.setattr(music, "now_playing", lambda: playing[0])
    monkeypatch.setattr(music, "command", sent.append)

    def start(uri):
        opened.append(uri)
        playing[0] = {"faixa": "Nova", "artista": "B"}
    monkeypatch.setattr(music.os, "startfile", start, raising=False)
    assert music.play_uri("spotify:track:X", wait=lambda s: None) == {"faixa": "Nova", "artista": "B"}
    assert sent == ["tocar_pausar"] and opened == ["spotify:track:X"]


def test_a_new_track_is_announced_once_with_its_cover(monkeypatch):
    import time as _t
    cards = []
    monkeypatch.setattr(music.BUS, "emit", lambda channel, text="", **extra: cards.append((channel, text, extra)))
    settings = type("S", (), {"get": lambda self, key: True})()
    vis = music.Visualizer(settings, find_cover=lambda song: "https://is1-ssl.mzstatic.com/a.jpg")
    song = {"artista": "Queen", "faixa": "Bohemian Rhapsody"}
    vis.announce(song); vis.announce(song); vis.announce(None)
    _t.sleep(0.2)
    assert cards == [("card", "Bohemian Rhapsody", {"kind": "music", "ok": True, "body": "Queen", "image": "https://is1-ssl.mzstatic.com/a.jpg"})]


def test_cover_comes_from_the_matching_itunes_result():
    import json
    data = {"results": [{"trackName": "Outra", "artworkUrl100": "https://x.mzstatic.com/a/100x100bb.jpg"},
                        {"trackName": "Tempo Perdido", "artworkUrl100": "https://x.mzstatic.com/b/100x100bb.jpg"}]}
    got = music.cover({"artista": "Legião Urbana", "faixa": "Tempo Perdido"}, get=lambda url, params: json.dumps(data))
    assert got == "https://x.mzstatic.com/b/300x300bb.jpg"
