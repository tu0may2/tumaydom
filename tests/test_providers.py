import pytest

from fitcoach.providers import PRESETS, build_provider, extract_json


def test_extract_json_from_fenced_block():
    assert extract_json('```json\n{"a": 1}\n```') == {"a": 1}


def test_extract_json_from_surrounding_prose():
    assert extract_json('Вот ответ: {"a": {"b": 2}} — готово') == {"a": {"b": 2}}


def test_extract_json_raises_on_garbage():
    with pytest.raises(ValueError, match="нет корректного JSON"):
        extract_json("никакого джейсона тут нет")


def test_unknown_provider_lists_available():
    with pytest.raises(ValueError, match="gemini"):
        build_provider("не-существует", "key")


@pytest.mark.parametrize("name", sorted(set(PRESETS) - {"anthropic"}))
def test_openai_compatible_presets_build(name):
    provider = build_provider(name, "test-key")
    assert provider.name == name
    assert provider.model == PRESETS[name]["model"]


def test_vision_capability_flags():
    assert build_provider("gemini", "k").supports_vision
    assert not build_provider("groq", "k").supports_vision


def test_explicit_model_and_base_url_win():
    provider = build_provider("openai", "k", model="my-model", base_url="http://localhost:8000/v1")
    assert provider.model == "my-model"


@pytest.mark.parametrize("model,expected", [
    ("gemma3:12b", True),
    ("llava:13b", True),
    ("qwen2.5vl:7b", True),
    ("qwen2.5:7b", False),
    ("llama3.1", False),
])
def test_ollama_vision_detected_by_model_tag(model, expected):
    assert build_provider("ollama", "", model=model).supports_vision is expected


def test_vision_override_wins_over_detection():
    assert build_provider("ollama", "", model="llama3.1", vision="on").supports_vision
    assert not build_provider("gemini", "k", vision="off").supports_vision


def test_ollama_needs_no_key():
    provider = build_provider("ollama", "")
    assert provider.model == PRESETS["ollama"]["model"]
