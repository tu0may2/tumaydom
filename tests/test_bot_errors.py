import pytest

from fitcoach.bot import _explain


@pytest.mark.parametrize("message,expected", [
    ("Connection error.", "Ollama не запущена"),
    ("Request timed out", "не успела ответить"),
    ("model 'gemma3' not found", "ollama pull"),
    ("Invalid JSON in response", "не удалось разобрать"),
])
def test_explain_translates_known_failures(message, expected):
    assert expected in _explain(Exception(message))


def test_explain_falls_back_to_raw_text():
    assert "странная поломка" in _explain(Exception("странная поломка"))
