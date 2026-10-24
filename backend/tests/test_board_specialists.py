"""Specialist loader tests (feature 026, T016).

Exercises ``app.services.board.specialists.load_roster`` against the
manifest fixtures under ``fixtures/board/specialists/``: invalid
manifests, root escape, missing default roles, an accepted extra custom
role, and roster-snapshot immutability across reloads.
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from app.services.board.specialists import SpecialistLoadError, load_roster
from tests.fixtures.board.paths import (
    INVALID_INCOMPATIBLE_ABILITY_ROOT,
    INVALID_MISSING_DEFAULT_ROLE_ROOT,
    INVALID_MISSING_FIELD_ROOT,
    INVALID_PATH_ESCAPE_ROOT,
    INVALID_UNKNOWN_CARD_TYPE_ROOT,
    VALID_SPECIALISTS_ROOT,
)

_FIXTURE_ROLE_IDS = frozenset(
    {"requester", "coder", "verifier", "input-security", "coordinator"}
)


class TestValidRoster:
    """A well-formed roster loads every role with its prompt content."""

    def test_loads_every_role(self) -> None:
        roster = load_roster(
            VALID_SPECIALISTS_ROOT, required_role_ids=_FIXTURE_ROLE_IDS
        )
        assert roster.ids() == _FIXTURE_ROLE_IDS

    def test_loads_prompt_content(self) -> None:
        roster = load_roster(
            VALID_SPECIALISTS_ROOT, required_role_ids=_FIXTURE_ROLE_IDS
        )
        assert "coder" in roster.get("coder").prompt.lower()

    def test_unknown_specialist_id_returns_none(self) -> None:
        roster = load_roster(
            VALID_SPECIALISTS_ROOT, required_role_ids=_FIXTURE_ROLE_IDS
        )
        assert roster.get("nonexistent") is None

    def test_accepts_an_extra_custom_role(self, tmp_path: Path) -> None:
        """A role beyond the required defaults is accepted, not rejected."""
        _copy_tree(VALID_SPECIALISTS_ROOT, tmp_path)
        custom = tmp_path / "custom-role"
        custom.mkdir()
        (custom / "manifest.toml").write_text(
            'id = "custom-role"\n'
            'label = "Custom"\n'
            'purpose = "An operator-added role."\n'
            'allowed_card_types = ["analysis"]\n'
            'required_abilities = ["text"]\n'
            'model_policy = "default"\n'
            'workspace_permission = "read_only"\n'
            "retry_limit = 1\n"
            'prompt_file = "prompt.md"\n'
        )
        (custom / "prompt.md").write_text("Custom role prompt.\n")

        roster = load_roster(tmp_path, required_role_ids=_FIXTURE_ROLE_IDS)

        assert "custom-role" in roster.ids()


class TestInvalidManifests:
    """Malformed manifests fail loudly rather than silently degrading."""

    def test_missing_required_field_is_rejected(self) -> None:
        with pytest.raises(SpecialistLoadError):
            load_roster(
                INVALID_MISSING_FIELD_ROOT,
                required_role_ids=frozenset({"broken"}),
            )

    def test_unsupported_card_type_is_rejected(self) -> None:
        with pytest.raises(SpecialistLoadError):
            load_roster(
                INVALID_UNKNOWN_CARD_TYPE_ROOT,
                required_role_ids=frozenset({"broken"}),
            )

    def test_incompatible_required_abilities_is_rejected(self) -> None:
        with pytest.raises(SpecialistLoadError):
            load_roster(
                INVALID_INCOMPATIBLE_ABILITY_ROOT,
                required_role_ids=frozenset({"broken"}),
            )

    def test_root_escaping_prompt_file_is_rejected(self) -> None:
        with pytest.raises(SpecialistLoadError):
            load_roster(
                INVALID_PATH_ESCAPE_ROOT,
                required_role_ids=frozenset({"broken"}),
            )

    def test_missing_default_role_is_rejected(self) -> None:
        with pytest.raises(SpecialistLoadError):
            load_roster(
                INVALID_MISSING_DEFAULT_ROLE_ROOT,
                required_role_ids=_FIXTURE_ROLE_IDS,
            )

    def test_nonexistent_root_is_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(SpecialistLoadError):
            load_roster(tmp_path / "does-not-exist")


class TestRosterImmutability:
    """A loaded roster is a frozen snapshot; reloading sees file changes."""

    def test_reload_reflects_a_changed_role_definition(
        self, tmp_path: Path
    ) -> None:
        original_limit, changed_limit = 2, 5
        _copy_tree(VALID_SPECIALISTS_ROOT, tmp_path)
        first = load_roster(tmp_path, required_role_ids=_FIXTURE_ROLE_IDS)
        assert first.get("coder").retry_limit == original_limit

        manifest = tmp_path / "coder" / "manifest.toml"
        manifest.write_text(
            manifest.read_text().replace(
                f"retry_limit = {original_limit}",
                f"retry_limit = {changed_limit}",
            )
        )
        second = load_roster(tmp_path, required_role_ids=_FIXTURE_ROLE_IDS)

        assert first.get("coder").retry_limit == original_limit
        assert second.get("coder").retry_limit == changed_limit


def _copy_tree(src: Path, dst: Path) -> None:
    """Copy a fixture specialist-root tree into a writable tmp directory."""
    for child in src.iterdir():
        target = dst / child.name
        if child.is_dir():
            shutil.copytree(child, target)
        else:
            shutil.copy2(child, target)
