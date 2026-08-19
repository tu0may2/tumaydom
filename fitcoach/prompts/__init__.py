"""Загрузка текстовых промптов из markdown-файлов рядом с модулем."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

_DIR = Path(__file__).parent


@lru_cache
def load(name: str) -> str:
    return (_DIR / f"{name}.md").read_text(encoding="utf-8").strip()


def coach_system() -> str:
    return load("coach")
