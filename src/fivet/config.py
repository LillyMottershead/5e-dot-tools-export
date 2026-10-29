"""Configuration and filesystem paths.

Config is TOML read by stdlib `tomllib` and validated by the pydantic already
required for the spell model, so this costs no extra dependency.

Note the contrast with `models.Spell`: that model allows unknown fields because
upstream data is not ours to control, whereas this one forbids them, because an
unknown key in a hand-written config file is a typo the user wants to hear
about rather than a setting that silently does nothing.
"""

from __future__ import annotations

import os
import tomllib
from enum import StrEnum
from pathlib import Path

import platformdirs
from pydantic import BaseModel, ConfigDict, Field, field_validator

from fivet.render.tags import LinkStyle

APP_NAME = "5et"

# Source abbreviations in preference order, newest core rules first. A source
# absent from this list sorts after every listed one, alphabetically, so
# resolution stays deterministic.
DEFAULT_SOURCE_PRIORITY = [
    "XPHB",
    "PHB",
    "XGE",
    "TCE",
    "SCC",
    "FTD",
    "EGW",
    "BMT",
    "AI",
    "LLK",
    "IDRotF",
    "SatO",
    "AAG",
    "AU",
    "EFA",
    "FRHoF",
    "GGR",
    "AitFR-AVT",
]


class Edition(StrEnum):
    """A rules edition, as selected by `--2014` or `--2024`.

    The two Player's Handbooks are the only pair of books that cover the same
    ground in both editions; every other source belongs to one edition or is
    edition-neutral. So scoping to an edition means excluding the other
    edition's PHB, not restricting to a single source: `--2014` keeps PHB and
    every supplement, `--2024` keeps XPHB and every supplement.
    """

    LEGACY = "2014"
    REVISED = "2024"

    @property
    def phb(self) -> str:
        """The Player's Handbook belonging to this edition."""
        return "PHB" if self is Edition.LEGACY else "XPHB"

    @property
    def excluded_source(self) -> str:
        """The Player's Handbook this edition rules out."""
        return "XPHB" if self is Edition.LEGACY else "PHB"


class Settings(BaseModel):
    """User settings, as read from config.toml."""

    model_config = ConfigDict(extra="forbid")

    links: LinkStyle = LinkStyle.WIKILINK
    source_priority: list[str] = Field(default_factory=lambda: list(DEFAULT_SOURCE_PRIORITY))
    template: str = "obsidian"
    fuzzy_cutoff: int = Field(default=80, ge=0, le=100)
    output_dir: Path | None = None

    @field_validator("output_dir")
    @classmethod
    def _expand(cls, value: Path | None) -> Path | None:
        return value.expanduser() if value is not None else None

    def source_rank(self, source: str) -> tuple[int, str]:
        """Sort key for choosing between same-named spells from different books.

        Listed sources rank by position; unlisted ones fall to the end in
        alphabetical order so the choice never depends on dict ordering.
        """
        upper = source.upper()
        for index, candidate in enumerate(self.source_priority):
            if candidate.upper() == upper:
                return (index, upper)
        return (len(self.source_priority), upper)


def cache_dir() -> Path:
    """Where fetched data and the index live. FIVET_CACHE_DIR overrides."""
    override = os.environ.get("FIVET_CACHE_DIR")
    if override:
        return Path(override).expanduser()
    return Path(platformdirs.user_cache_dir(APP_NAME))


def config_dir() -> Path:
    """Where config.toml and user templates live. FIVET_CONFIG_DIR overrides."""
    override = os.environ.get("FIVET_CONFIG_DIR")
    if override:
        return Path(override).expanduser()
    return Path(platformdirs.user_config_dir(APP_NAME))


def config_path() -> Path:
    return config_dir() / "config.toml"


def template_dir() -> Path:
    """User template overrides, which shadow the shipped ones by name."""
    return config_dir() / "templates"


def load_settings(path: Path | None = None) -> Settings:
    """Load settings, falling back to defaults when no config file exists."""
    path = path or config_path()
    if not path.is_file():
        return Settings()
    with path.open("rb") as handle:
        data = tomllib.load(handle)
    return Settings.model_validate(data)
