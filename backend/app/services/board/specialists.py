"""File-backed specialist roster loader (feature 026, FR-007, FR-009).

Loads and strictly validates every role under ``specialists_root`` into an
immutable :class:`SpecialistRoster` snapshot. Rejects, before any card can
be dispatched to it, a definition with a missing required field, an
unsupported card type, an incompatible required ability, an unsafe
workspace permission, a manifest id that doesn't match its directory, or a
``prompt_file`` that resolves outside the specialist root.
"""
from __future__ import annotations

import tomllib
from pathlib import Path

from app.backends.base import Capability
from app.models_board import CardKind, SpecialistDefinition, WorkspacePermission

#: The roles this feature ships by default (FR-008); a loaded roster must
#: contain at least these, though an operator may add more.
DEFAULT_ROLE_IDS = frozenset(
    {
        "requester",
        "pm",
        "uiux",
        "developer",
        "infosec",
        "dba",
        "architect",
        "ops",
        "qa",
        "coordinator",
        "coder",
        "verifier",
        "input-security",
    }
)

_REQUIRED_FIELDS = frozenset(
    {
        "id",
        "label",
        "purpose",
        "allowed_card_types",
        "required_abilities",
        "model_policy",
        "workspace_permission",
        "retry_limit",
        "prompt_file",
    }
)
_VALID_CARD_KINDS = frozenset(k.value for k in CardKind)
_VALID_ABILITIES = frozenset(c.value for c in Capability)
_VALID_WORKSPACE_PERMISSIONS = frozenset(p.value for p in WorkspacePermission)


class SpecialistLoadError(Exception):
    """Raised when the specialist roster fails to load or validate."""


class SpecialistRoster:
    """An immutable snapshot of the loaded, validated specialist roster."""

    def __init__(self, specialists: dict[str, SpecialistDefinition]) -> None:
        self._specialists = dict(specialists)

    def get(self, specialist_id: str) -> SpecialistDefinition | None:
        """Return one specialist by id, or ``None`` if it is not in the
        roster."""
        return self._specialists.get(specialist_id)

    def ids(self) -> frozenset[str]:
        """Every specialist id in this snapshot."""
        return frozenset(self._specialists)


def load_roster(
    specialists_root: str | Path,
    *,
    required_role_ids: frozenset[str] = DEFAULT_ROLE_IDS,
) -> SpecialistRoster:
    """Load and validate every role under *specialists_root*.

    :param specialists_root: Root directory; one subdirectory per role.
    :param required_role_ids: Role ids that must be present, else loading
        fails (defaults to :data:`DEFAULT_ROLE_IDS`).
    :raises SpecialistLoadError: If the root is missing, a manifest is
        malformed or unsafe, or a required role is absent.
    """
    root = Path(specialists_root).resolve()
    if not root.is_dir():
        raise SpecialistLoadError(f"specialists_root not found: {root}")
    specialists = {
        entry.name: _load_one(root, entry)
        for entry in sorted(root.iterdir())
        if entry.is_dir()
    }
    missing = required_role_ids - specialists.keys()
    if missing:
        raise SpecialistLoadError(
            f"missing required default role(s): {', '.join(sorted(missing))}"
        )
    return SpecialistRoster(specialists)


def _load_one(root: Path, entry: Path) -> SpecialistDefinition:
    """Parse, validate, and return one role's :class:`SpecialistDefinition`."""
    manifest_path = entry / "manifest.toml"
    if not manifest_path.is_file():
        raise SpecialistLoadError(f"{entry.name}: missing manifest.toml")
    try:
        data = tomllib.loads(manifest_path.read_text())
    except tomllib.TOMLDecodeError as exc:
        raise SpecialistLoadError(f"{entry.name}: invalid TOML: {exc}") from exc
    _validate_manifest_shape(entry.name, data)
    prompt = _load_prompt(root, entry, data["prompt_file"])
    return SpecialistDefinition(
        id=data["id"],
        label=data["label"],
        purpose=data["purpose"],
        allowed_card_types=tuple(data["allowed_card_types"]),
        required_abilities=tuple(data["required_abilities"]),
        model_policy=data["model_policy"],
        workspace_permission=data["workspace_permission"],
        retry_limit=data["retry_limit"],
        prompt=prompt,
    )


def _validate_manifest_shape(dir_name: str, data: dict[str, object]) -> None:
    """Validate required fields, id/directory match, and closed vocabularies."""
    missing_fields = _REQUIRED_FIELDS - data.keys()
    if missing_fields:
        raise SpecialistLoadError(
            f"{dir_name}: missing required field(s): "
            f"{', '.join(sorted(missing_fields))}"
        )
    if data["id"] != dir_name:
        raise SpecialistLoadError(
            f"{dir_name}: manifest id {data['id']!r} does not match "
            f"its directory name"
        )
    unknown_kinds = set(data["allowed_card_types"]) - _VALID_CARD_KINDS
    if unknown_kinds:
        raise SpecialistLoadError(
            f"{dir_name}: unsupported card type(s): "
            f"{', '.join(sorted(unknown_kinds))}"
        )
    unknown_abilities = set(data["required_abilities"]) - _VALID_ABILITIES
    if unknown_abilities:
        raise SpecialistLoadError(
            f"{dir_name}: unsupported required_abilities: "
            f"{', '.join(sorted(unknown_abilities))}"
        )
    _validate_workspace_permission(dir_name, data)


def _validate_workspace_permission(
    dir_name: str, data: dict[str, object]
) -> None:
    """Reject an unknown or unsafe ``workspace_permission`` value."""
    permission = data["workspace_permission"]
    if permission not in _VALID_WORKSPACE_PERMISSIONS:
        raise SpecialistLoadError(
            f"{dir_name}: unknown workspace_permission: {permission!r}"
        )
    needs_file_edits = permission == WorkspacePermission.WRITE.value
    if needs_file_edits and Capability.FILE_EDITS.value not in (
        data["required_abilities"]
    ):
        raise SpecialistLoadError(
            f"{dir_name}: workspace_permission 'write' requires the "
            f"'{Capability.FILE_EDITS.value}' ability"
        )


def _load_prompt(root: Path, entry: Path, prompt_file: str) -> str:
    """Read *prompt_file*, refusing to resolve outside *root*."""
    candidate = (entry / prompt_file).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise SpecialistLoadError(
            f"{entry.name}: prompt_file escapes specialists_root: "
            f"{prompt_file}"
        ) from exc
    if not candidate.is_file():
        raise SpecialistLoadError(
            f"{entry.name}: prompt_file not found: {prompt_file}"
        )
    return candidate.read_text()
