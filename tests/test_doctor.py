from fitcoach.doctor import PROBE_SCHEMA, _hint


def test_probe_schema_is_strict():
    assert PROBE_SCHEMA["additionalProperties"] is False
    assert set(PROBE_SCHEMA["required"]) == set(PROBE_SCHEMA["properties"])


def test_hint_for_dead_ollama(capsys):
    _hint("ollama", Exception("Connection error."))
    assert "ollama serve" in capsys.readouterr().out


def test_hint_for_missing_model(capsys):
    _hint("ollama", Exception("model 'gemma3' not found"))
    assert "ollama pull" in capsys.readouterr().out


def test_hint_for_bad_key(capsys):
    _hint("gemini", Exception("401 invalid api key"))
    assert "ключ" in capsys.readouterr().out


def test_hint_stays_silent_when_unclear(capsys):
    _hint("gemini", Exception("странная ошибка"))
    assert capsys.readouterr().out == ""
