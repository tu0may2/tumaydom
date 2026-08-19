from fitcoach.db import DIALOG_CHARS, DIALOG_KEEP, DIALOG_TURNS, Database
from fitcoach.ingest.parser import looks_like_question


def test_dialog_returns_last_turns_in_order(tmp_path):
    db = Database(tmp_path / "t.db")
    for i in range(5):
        db.add_dialog(1, "user", f"вопрос {i}")
        db.add_dialog(1, "assistant", f"ответ {i}")

    history = db.recent_dialog(1)
    assert len(history) == DIALOG_TURNS
    assert history[-1] == {"role": "assistant", "content": "ответ 4"}
    # Порядок хронологический: самая старая уцелевшая реплика идёт первой.
    assert [turn["role"] for turn in history[:2]] == ["user", "assistant"]
    assert history[0]["content"] == "вопрос 1"


def test_dialog_is_pruned_and_truncated(tmp_path):
    db = Database(tmp_path / "t.db")
    db.add_dialog(1, "assistant", "я" * (DIALOG_CHARS + 500))
    for i in range(DIALOG_KEEP + 20):
        db.add_dialog(1, "user", f"реплика {i}")

    with db.connect() as conn:
        total = conn.execute("SELECT COUNT(*) c FROM dialog WHERE user_id = 1").fetchone()["c"]
    assert total == DIALOG_KEEP

    db.add_dialog(2, "assistant", "я" * (DIALOG_CHARS + 500))
    assert len(db.recent_dialog(2)[0]["content"]) == DIALOG_CHARS


def test_dialog_is_per_user(tmp_path):
    db = Database(tmp_path / "t.db")
    db.add_dialog(1, "user", "моё")
    db.add_dialog(2, "user", "чужое")
    assert db.recent_dialog(1) == [{"role": "user", "content": "моё"}]


def test_clear_dialog_keeps_workouts(tmp_path):
    db = Database(tmp_path / "t.db")
    db.add_workout(1, {"date": "2026-08-18", "kind": "strength"})
    db.add_dialog(1, "user", "привет")
    db.clear_dialog(1)
    assert db.recent_dialog(1) == []
    assert len(db.recent_workouts(1)) == 1


def test_questions_take_the_fast_path():
    assert looks_like_question("Видео с тренировкой примешь?")
    assert looks_like_question("что поесть после тренировки")
    assert looks_like_question("посоветуй разминку")


def test_data_messages_go_to_full_parsing():
    assert not looks_like_question("жим 80x5x5 rpe 8")
    assert not looks_like_question("сегодня присед 100 на 5")
    assert not looks_like_question("спал 7 часов, вес 82")
    assert not looks_like_question("")
