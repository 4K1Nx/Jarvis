from viv.memory import Memory


def test_remember_persists_across_instances(tmp_path):
    path = str(tmp_path / "m.json")
    Memory(path).remember("gosta de café")
    assert Memory(path).facts() == ["gosta de café"]


def test_remember_ignores_duplicates_and_blank(tmp_path):
    m = Memory(str(tmp_path / "m.json"))
    m.remember("gosta de café"); m.remember("gosta de café"); m.remember("   ")
    assert m.facts() == ["gosta de café"]


def test_forget_removes_only_matching_facts(tmp_path):
    m = Memory(str(tmp_path / "m.json"))
    m.remember("gosta de café"); m.remember("mora em Recife")
    m.forget("CAFÉ")
    assert m.facts() == ["mora em Recife"]


def test_recent_turns_returns_last_n(tmp_path):
    m = Memory(str(tmp_path / "m.json"))
    for i in range(4):
        m.add_turn("user", f"fala {i}")
    assert [t["text"] for t in m.recent_turns(2)] == ["fala 2", "fala 3"]
    assert m.recent_turns(2)[0]["role"] == "user"


def test_turn_log_is_bounded(tmp_path):
    m = Memory(str(tmp_path / "m.json"))
    for i in range(300):
        m.add_turn("viv", str(i))
    assert len(Memory(str(tmp_path / "m.json")).recent_turns(1000)) == 100


def test_corrupt_file_becomes_empty_memory(tmp_path):
    path = tmp_path / "m.json"
    path.write_text("{isso não é json", encoding="utf-8")
    m = Memory(str(path))
    assert m.facts() == [] and m.recent_turns(5) == []


def test_prompt_block_contains_facts_and_turns(tmp_path):
    m = Memory(str(tmp_path / "m.json"))
    m.remember("gosta de café"); m.add_turn("user", "bom dia")
    block = m.prompt_block(5)
    assert "gosta de café" in block and "bom dia" in block
