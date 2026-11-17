"""Apps da Viv: projetos web servidos por ela e ligados ao vivo (viv/apps.py, web/viv-app.js)."""
import json
import threading

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from viv.apps import AppHub, create_apps_app
from viv.tools import code, registry
from viv.tools.registry import Context

PORT = 8766
ORIGIN = {"origin": f"http://127.0.0.1:{PORT}"}


@pytest.fixture
def projects(tmp_path):
    xadrez = tmp_path / "xadrez-viv"
    (xadrez / ".viv").mkdir(parents=True)
    (xadrez / "index.html").write_text('<script src="/apps/viv-app.js"></script>', encoding="utf-8")
    (xadrez / "jogo.js").write_text("// jogo", encoding="utf-8")
    (xadrez / ".viv" / "meta.json").write_text("{}", encoding="utf-8")
    (tmp_path / "segredo.txt").write_text("não", encoding="utf-8")
    return tmp_path


def make(projects, events=None):
    hub = AppHub(on_event=(lambda slug, text, state: events.append((slug, text, state))) if events is not None else None)
    return hub, create_apps_app(hub, lambda: projects, PORT)


def test_serves_project_files_and_the_library_but_nothing_outside(projects):
    _, app = make(projects)
    client = TestClient(app)
    assert "viv-app.js" in client.get("/apps/xadrez-viv/").text
    assert client.get("/apps/xadrez-viv/jogo.js").text == "// jogo"
    assert "window.Viv" in client.get("/apps/viv-app.js").text
    for path in ("/apps/xadrez-viv/.viv/meta.json", "/apps/xadrez-viv/..%2Fsegredo.txt", "/apps/..%2F/segredo.txt",
                 "/apps/nao-existe/", "/apps/xadrez-viv/%2E%2E/segredo.txt"):
        assert client.get(path).status_code == 404, path


def test_bridge_refuses_other_origins(projects):
    _, app = make(projects)
    with TestClient(app) as client:
        for origin in ({"origin": "http://127.0.0.1:8765"}, {"origin": "https://exemplo.com"}, {}):
            with pytest.raises(WebSocketDisconnect):
                with client.websocket_connect("/apps/xadrez-viv/ws", headers=origin) as socket:
                    socket.receive_text()


def test_app_tells_viv_what_happens_and_obeys_her_commands(projects):
    events = []
    hub, app = make(projects, events)
    with TestClient(app) as client, client.websocket_connect("/apps/xadrez-viv/ws", headers=ORIGIN) as socket:
        socket.send_text(json.dumps({"type": "acoes", "acoes": {"mover": "dados {de, para}"}}))
        socket.send_text(json.dumps({"type": "evento", "texto": "O jogador moveu e2 para e4",
                                     "dados": {"fen": "x", "vez": "pretas"}}))
        socket.send_text(json.dumps({"type": "evento", "texto": "logo em seguida"}))   # perto demais: vem depois
        socket.send_text(json.dumps({"type": "evento", "texto": "xeque", "dados": {"fen": "x", "vez": "pretas"}}))
        socket.send_text("isso não é json")
        socket.send_text(json.dumps({"type": "estado", "dados": {"grande": "x" * 30000}}))   # grande demais: ignorado
        for _ in range(100):
            if hub.connected("xadrez-viv") and len(events) >= 2:
                break
            threading.Event().wait(0.02)
        # o primeiro chega na hora; os seguintes, juntos num só aviso, sem se perder
        assert events == [("xadrez-viv", "O jogador moveu e2 para e4", {"fen": "x", "vez": "pretas"}),
                          ("xadrez-viv", "logo em seguida; xeque", {"fen": "x", "vez": "pretas"})]
        info = hub.snapshot("xadrez-viv")
        assert info["acoes"] == {"mover": "dados {de, para}"} and info["estado"] == {"fen": "x", "vez": "pretas"}

        answers = []
        worker = threading.Thread(target=lambda: answers.append(hub.command("xadrez-viv", "mover", {"de": "e7", "para": "e5"})))
        worker.start()
        sent = json.loads(socket.receive_text())
        assert sent["type"] == "comando" and sent["acao"] == "mover" and sent["dados"] == {"de": "e7", "para": "e5"}
        socket.send_text(json.dumps({"type": "resposta", "id": sent["id"], "ok": False, "erro": "jogada ilegal"}))
        worker.join(5)
        assert answers == [{"ok": False, "erro": "jogada ilegal"}]


def test_command_without_an_open_app_says_so():
    with pytest.raises(RuntimeError, match="não está aberto"):
        AppHub().command("xadrez-viv", "mover", {})


class Hub:
    def __init__(self):
        self.sent = []

    def command(self, slug, action, data, timeout=6.0):
        self.sent.append((slug, action, data))
        return {"ok": action == "mover", "erro": "" if action == "mover" else "ação desconhecida"}

    def snapshot(self, slug):
        return {"conectado": True, "estado": {"vez": "brancas"}, "acoes": {"mover": "{de, para}"}, "eventos": ["O jogador moveu"]}


def test_viv_tools_read_state_and_send_commands(projects, monkeypatch):
    registry.load_all()
    hub, opened = Hub(), []
    monkeypatch.setattr(code, "workspace", lambda: projects)
    monkeypatch.setattr(code.webbrowser, "open", opened.append)
    ctx = Context({"server": {"port": 8765}}, apps=hub)
    assert "ligado a você" in registry.call("app_abrir", {"projeto": "Xadrez Viv"}, ctx)
    assert opened == ["http://127.0.0.1:8766/apps/xadrez-viv/"]
    state = registry.call("app_estado", {"projeto": "xadrez viv"}, ctx)
    assert "mover: {de, para}" in state and '"vez": "brancas"' in state and "O jogador moveu" in state
    assert registry.call("app_enviar", {"projeto": "xadrez viv", "acao": "mover", "dados": '{"de": "e7", "para": "e5"}'},
                         ctx).startswith("feito.")
    assert "ação desconhecida" in registry.call("app_enviar", {"projeto": "xadrez viv", "acao": "pular"}, ctx)
    assert registry.call("app_enviar", {"projeto": "xadrez viv", "acao": "mover", "dados": "{e7"}, ctx).startswith("erro:")
    assert hub.sent == [("xadrez-viv", "mover", {"de": "e7", "para": "e5"}), ("xadrez-viv", "pular", {})]
