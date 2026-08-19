from fitcoach.config import Settings


def test_provider_key_picked_from_native_env(monkeypatch):
    monkeypatch.setenv("FITCOACH_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "g-key")
    monkeypatch.delenv("FITCOACH_API_KEY", raising=False)
    settings = Settings(_env_file=None)
    assert settings.api_key == "g-key"


def test_generic_key_wins(monkeypatch):
    monkeypatch.setenv("FITCOACH_PROVIDER", "GROQ")
    monkeypatch.setenv("FITCOACH_API_KEY", "generic")
    monkeypatch.setenv("GROQ_API_KEY", "native")
    settings = Settings(_env_file=None)
    assert settings.provider == "groq"
    assert settings.api_key == "generic"


def test_hhmm_parsing():
    assert Settings(_env_file=None).hhmm("07:30") == (7, 30)
