"""Path helpers for the board fixture tree under ``fixtures/board/``.

Specialist-manifest fixtures exercise the file-backed roster loader
(``app/services/board/specialists.py``); input fixtures exercise the
untrusted-input quarantine boundary (``app/services/board/quarantine.py``).
"""
from __future__ import annotations

from pathlib import Path

BOARD_FIXTURES_DIR = Path(__file__).parent
SPECIALISTS_FIXTURES_DIR = BOARD_FIXTURES_DIR / "specialists"
INPUT_FIXTURES_DIR = BOARD_FIXTURES_DIR / "input"

#: A complete, valid mini-roster covering every permission/ability
#: combination this feature's default roles use.
VALID_SPECIALISTS_ROOT = SPECIALISTS_FIXTURES_DIR / "valid"

#: One malformed-roster directory per invalid-manifest case: each is a copy
#: of the valid roster with exactly one role replaced by a "broken" one, so
#: a loader test can assert on that single violation.
INVALID_MISSING_FIELD_ROOT = SPECIALISTS_FIXTURES_DIR / "invalid_missing_field"
INVALID_UNKNOWN_CARD_TYPE_ROOT = (
    SPECIALISTS_FIXTURES_DIR / "invalid_unknown_card_type"
)
INVALID_INCOMPATIBLE_ABILITY_ROOT = (
    SPECIALISTS_FIXTURES_DIR / "invalid_incompatible_ability"
)
INVALID_PATH_ESCAPE_ROOT = SPECIALISTS_FIXTURES_DIR / "invalid_path_escape"
INVALID_MISSING_DEFAULT_ROLE_ROOT = (
    SPECIALISTS_FIXTURES_DIR / "invalid_missing_default_role"
)


def read_input_fixture(name: str) -> str:
    """Return the text content of one input fixture by file name.

    :param name: File name under ``fixtures/board/input/``, e.g.
        ``"safe_task_body.txt"``.
    """
    return (INPUT_FIXTURES_DIR / name).read_text()
