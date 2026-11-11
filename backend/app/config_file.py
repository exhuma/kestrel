"""The TOML config file as a pydantic-settings source.

``KESTREL_CONFIG_FILE`` names a TOML file whose top-level keys are
:class:`app.config.Settings` fields, so every setting can come from the
file; nothing has to be registered here when a setting is added.
"""
from __future__ import annotations

import logging
import tomllib
from pathlib import Path

from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    TomlConfigSettingsSource,
)

_log = logging.getLogger("kestrel.config")


class ConfigFileSource(TomlConfigSettingsSource):
    """Values from the TOML config file, validated strictly.

    A missing file, malformed TOML and a top-level key that is no setting
    all raise :class:`ValueError`, so a typo or a wrong path fails at
    startup instead of being silently ignored.
    """

    def __init__(self, settings_cls: type[BaseSettings], path: Path) -> None:
        """
        :param settings_cls: The settings class the keys must belong to.
        :param path: The TOML file to read.
        :raises ValueError: If the file is missing, is not valid TOML, or
            has a top-level key that is not a setting.
        """
        if not path.is_file():
            raise ValueError(f"config_file not found: {path}")
        _log.info("loading config file: %s", path.resolve())
        try:
            super().__init__(settings_cls, toml_file=path)
        except tomllib.TOMLDecodeError as exc:
            raise ValueError(f"invalid TOML in {path}: {exc}") from exc
        unknown = sorted(set(self.toml_data) - set(settings_cls.model_fields))
        if unknown:
            raise ValueError(
                f"unknown setting(s) in {path}: {', '.join(unknown)}"
            )


def config_file_source(
    settings_cls: type[BaseSettings],
    *locators: PydanticBaseSettingsSource,
) -> PydanticBaseSettingsSource | None:
    """Build the config-file source, or ``None`` when no file is named.

    :param settings_cls: The settings class the file configures.
    :param locators: Sources consulted, in order, for the ``config_file``
        setting (``KESTREL_CONFIG_FILE``); the first that sets it wins.
    :returns: The source, or ``None`` if no ``config_file`` is set.
    """
    for locator in locators:
        path = locator().get("config_file")
        if path:
            return ConfigFileSource(settings_cls, Path(str(path)))
    _log.info(
        "no config file configured (KESTREL_CONFIG_FILE unset) — "
        "using built-in defaults"
    )
    return None
