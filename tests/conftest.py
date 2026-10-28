"""Shared fixtures.

Spell fixtures are hand-written to exercise schema shapes confirmed in the real
data. No spell text is copied from upstream (docs/DESIGN.md section 2).
"""

from pathlib import Path

import pytest


@pytest.fixture
def isolated_dirs(tmp_path, monkeypatch):
    """Point cache and config at a temp dir so tests never touch real ones."""
    cache = tmp_path / "cache"
    config = tmp_path / "config"
    cache.mkdir()
    config.mkdir()
    monkeypatch.setenv("FIVET_CACHE_DIR", str(cache))
    monkeypatch.setenv("FIVET_CONFIG_DIR", str(config))
    return {"cache": cache, "config": config}


@pytest.fixture
def raw_spell() -> dict:
    """A levelled spell with scaling, matching the shape of a real record."""
    return {
        "name": "Test Blast",
        "source": "XPHB",
        "page": 100,
        "level": 3,
        "school": "V",
        "time": [{"number": 1, "unit": "action"}],
        "range": {"type": "point", "distance": {"type": "feet", "amount": 150}},
        "components": {"v": True, "s": True, "m": "a scrap of parchment"},
        "duration": [{"type": "instant"}],
        "entries": [
            "Each creature in the area makes a Dexterity saving throw, "
            "taking {@damage 8d6} Fire damage on a failure.",
            "Flammable objects start {@hazard burning|XPHB}.",
        ],
        "entriesHigherLevel": [
            {
                "type": "entries",
                "name": "Using a Higher-Level Spell Slot",
                "entries": ["The damage increases by {@scaledamage 8d6|3-9|1d6} per slot level."],
            }
        ],
        "damageInflict": ["fire"],
        "savingThrow": ["dexterity"],
        "areaTags": ["S"],
    }


@pytest.fixture
def raw_cantrip() -> dict:
    """A concentration ritual cantrip, to cover the flag-bearing fields."""
    return {
        "name": "Test Touch",
        "source": "PHB",
        "page": 10,
        "level": 0,
        "school": "T",
        "time": [{"number": 1, "unit": "action"}],
        "range": {"type": "point", "distance": {"type": "touch"}},
        "components": {"v": True},
        "duration": [
            {"type": "timed", "duration": {"type": "minute", "amount": 1}, "concentration": True}
        ],
        "meta": {"ritual": True},
        "entries": ["You touch a creature."],
    }


@pytest.fixture
def write_config(isolated_dirs):
    """Write a config.toml into the isolated config dir."""

    def _write(body: str) -> Path:
        path = isolated_dirs["config"] / "config.toml"
        path.write_text(body)
        return path

    return _write
