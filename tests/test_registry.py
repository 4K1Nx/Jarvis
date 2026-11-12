import pytest
from viv.bus import BUS
from viv.tools import registry
from viv.tools.registry import Context, tool

CFG = {"safety": {"dangerous": ["system_power"]}}


@pytest.fixture
def cards(monkeypatch):
    seen = []
    monkeypatch.setattr(BUS, "emit", lambda channel, text="", **extra: seen.append((channel, text, extra)))
    return seen


@pytest.fixture(autouse=True)
def fake_tools():
    @tool("t_soma", "Soma dois números.", {"a": {"type": "integer"}, "b": {"type": "integer", "required": False}})
    def soma(a, b=1, ctx=None):
        return str(a + b)

    @tool("t_quebra", "Sempre falha.", {})
    def quebra(ctx=None):
        raise RuntimeError("x")

    yield
    registry._REG.pop("t_soma"); registry._REG.pop("t_quebra")


def decl(name):
    return next(d for d in registry.declarations() if d["name"] == name)


def test_declaration_lists_only_required_params():
    d = decl("t_soma")
    assert d["parameters"]["required"] == ["a"]
    assert set(d["parameters"]["properties"]) == {"a", "b"}
    assert "required" not in d["parameters"]["properties"]["b"]


def test_call_runs_tool():
    assert registry.call("t_soma", {"a": 2, "b": 3}, Context(CFG)) == "5"


def test_unknown_tool_returns_error_text():
    assert registry.call("inexistente", {}, Context(CFG)).startswith("erro:")


@pytest.mark.parametrize("args", [{}, {"a": 1, "zzz": 2}, None, {"a": "abc", "b": 2}, "texto"])
def test_malformed_args_return_error_text(args):
    assert registry.call("t_soma", args, Context(CFG)).startswith("erro:")


def test_tool_exception_becomes_error_and_failed_card(cards):
    assert registry.call("t_quebra", {}, Context(CFG)) == "erro: x"
    assert any(ch == "card" and extra.get("ok") is False for ch, _, extra in cards)


def test_is_dangerous_from_config():
    assert registry.is_dangerous("system_power", CFG) is True
    assert registry.is_dangerous("t_soma", CFG) is False
