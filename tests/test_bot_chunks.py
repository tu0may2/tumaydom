from fitcoach.bot import _chunks

LIMIT = 4000


def test_short_text_is_single_chunk():
    assert _chunks("привет", LIMIT) == ["привет"]


def test_long_paragraph_is_hard_split():
    parts = _chunks("a" * 9000, LIMIT)
    assert [len(p) for p in parts] == [4000, 4000, 1000]


def test_no_empty_chunks_and_limit_respected():
    text = ("абзац " * 300 + "\n") * 8
    parts = _chunks(text, LIMIT)
    assert all(part.strip() for part in parts)
    assert all(len(part) <= LIMIT for part in parts)
