import pytest

from viv.errors import ERRORS


@pytest.fixture(autouse=True)
def isolated_error_log(tmp_path, monkeypatch):
    """Os testes provocam erros de propósito; eles não podem cair no log real do usuário."""
    monkeypatch.setattr(ERRORS, "path", tmp_path / "erros.jsonl")
