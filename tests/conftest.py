import pytest

from viv.errors import ERRORS


@pytest.fixture(autouse=True)
def isolated_error_log(tmp_path, monkeypatch):
    """Os testes provocam erros de propósito; eles não podem cair no log real do usuário."""
    monkeypatch.setattr(ERRORS, "path", tmp_path / "erros.jsonl")


@pytest.fixture(autouse=True)
def no_real_ollama(monkeypatch):
    """Os testes nunca falam com o Ollama de verdade: sem isto, um modelo instalado responderia no lugar do falso."""
    from viv.tools import local

    def offline(*args, **kwargs):
        raise OSError("Ollama fora do ar (teste)")
    monkeypatch.setattr(local, "_http", offline)


@pytest.fixture(autouse=True)
def isolated_material_records(tmp_path, monkeypatch):
    """Os registros de materiais criados nos testes não podem cair na pasta data/ do usuário."""
    from viv.tools import docs
    monkeypatch.setattr(docs, "RECORDS", tmp_path / "materiais")
