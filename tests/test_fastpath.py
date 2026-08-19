import pytest

from fitcoach.bot import _greeting_reply
from fitcoach.db import Database
from fitcoach.ingest.parser import is_greeting, looks_like_question


@pytest.mark.parametrize("text", ["привет", "Привет!", "спасибо", "ок", "Добрый вечер",
                                  "тест", "ага"])
def test_greetings_need_no_model(text):
    assert is_greeting(text)


@pytest.mark.parametrize("text", ["привет, что по плану на сегодня", "жим 80x5x5",
                                  "спасибо, а сколько белка", ""])
def test_non_greetings_are_not_matched(text):
    assert not is_greeting(text)


@pytest.mark.parametrize("text", ["что поесть после тренировки", "а если наоборот делать",
                                  "ну как дела", "посоветуй разминку"])
def test_chatter_takes_the_single_call_path(text):
    assert looks_like_question(text)


@pytest.mark.parametrize("text", [
    "жим 80x5x5 rpe 8",          # цифры — всегда полный разбор
    "моя цель набрать массу",     # данные профиля без цифр
    "тренируюсь дома с гантелями",
    "спал плохо",
    "бег даётся тяжело",
])
def test_diary_data_still_goes_to_full_parsing(text):
    assert not looks_like_question(text)


def test_greeting_reply_asks_newcomer_about_profile(tmp_path):
    db = Database(tmp_path / "t.db")
    assert "Расскажи о себе" in _greeting_reply(db, 1)


def test_greeting_reply_names_today_session(tmp_path):
    db = Database(tmp_path / "t.db")
    db.update_profile(1, {"goal": "сила"})
    db.save_plan(1, "2026-08-17", {"days": [
        {"weekday": "wed", "kind": "strength", "title": "Ноги A", "blocks": []}]})

    reply = _greeting_reply(db, 1)
    assert "Ноги A" in reply or "Присылай тренировку" in reply  # зависит от дня недели


def test_greeting_reply_on_rest_day(tmp_path):
    db = Database(tmp_path / "t.db")
    db.update_profile(1, {"goal": "сила"})
    from datetime import date
    weekday = date.today().strftime("%a").lower()[:3]
    db.save_plan(1, "2026-08-17", {"days": [
        {"weekday": weekday, "kind": "rest", "title": "Отдых", "blocks": []}]})
    assert "отдых" in _greeting_reply(db, 1).lower()
