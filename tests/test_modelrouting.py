import modelrouting
from modelrouting import Route, Routing


def test_roundtrip(data_dir):
    r = Routing(
        tasks={"cover_letter": Route("claude", "claude-opus-4-8")},
        agent=Route("claude", ""),
        default=Route("codex", "gpt-4o", context_window=200000),
    )
    modelrouting.save(r)
    loaded = modelrouting.load()
    assert loaded.default == Route("codex", "gpt-4o", context_window=200000)
    assert loaded.tasks["cover_letter"].model == "claude-opus-4-8"
    assert loaded.tasks["cover_letter"].context_window == 0


def test_from_dict_legacy_without_context_window(data_dir):
    route = Route.from_dict({"connection": "claude", "model": "claude-opus-4-8"})
    assert route.context_window == 0


def test_load_missing_file_gives_empty(data_dir):
    r = modelrouting.load()
    assert r.tasks == {} and r.agent is None and r.default is None


def test_from_dict_ignores_garbage(data_dir):
    r = Routing.from_dict({"tasks": {"keywords": {"connection": 5}}, "default": "nope", "junk": 1})
    assert r.tasks == {} and r.default is None


def test_resolve_ladder():
    r = Routing(tasks={"keywords": Route("ollama", "llama3.1")}, agent=None, default=Route("claude"))
    assert modelrouting.resolve(r, "keywords").connection == "ollama"
    assert modelrouting.resolve(r, "tailor").connection == "claude"
    assert modelrouting.resolve(r, None).connection == "claude"
    assert modelrouting.resolve(Routing(), "keywords") is None
