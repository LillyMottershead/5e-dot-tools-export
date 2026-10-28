"""The spell model.

Deliberately lax, per docs/DESIGN.md section 4.3: only the fields this tool
renders are declared, everything optional carries a default, and unknown fields
are kept rather than rejected. Upstream ships weekly across 18 source books
with a decade of accumulated inconsistency, so a model that rejects surprises
would break `sync` regularly for no benefit.

Ten fields are present on all 969 spells (name, source, page, level, school,
time, range, components, duration, entries). Of those, only name, source and
level are required here, because they are what identity and filtering depend
on. If upstream ever drops `school` from a record we would rather render an
empty school than refuse to show the spell.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from fivet import normalize


class Spell(BaseModel):
    """One spell, as stored in data/spells/spells-<source>.json."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    name: str
    source: str
    level: int

    page: int | None = None
    school: str | None = None
    time: list[dict[str, Any]] = Field(default_factory=list)
    range: dict[str, Any] | None = None
    components: dict[str, Any] | None = None
    duration: list[dict[str, Any]] = Field(default_factory=list)
    entries: list[Any] = Field(default_factory=list)
    entries_higher_level: list[Any] = Field(default_factory=list, alias="entriesHigherLevel")
    meta: dict[str, Any] | None = None
    other_sources: list[dict[str, Any]] = Field(default_factory=list, alias="otherSources")
    subschools: list[str] = Field(default_factory=list)

    # Derived index tags upstream computes for its own filters. Useful for
    # search, never rendered as prose.
    damage_inflict: list[str] = Field(default_factory=list, alias="damageInflict")
    condition_inflict: list[str] = Field(default_factory=list, alias="conditionInflict")
    saving_throw: list[str] = Field(default_factory=list, alias="savingThrow")
    ability_check: list[str] = Field(default_factory=list, alias="abilityCheck")
    spell_attack: list[str] = Field(default_factory=list, alias="spellAttack")
    area_tags: list[str] = Field(default_factory=list, alias="areaTags")
    misc_tags: list[str] = Field(default_factory=list, alias="miscTags")

    # Populated from data/spells/sources.json at index time, not present on the
    # spell record itself.
    classes: list[str] = Field(default_factory=list)

    @property
    def school_full(self) -> str:
        return normalize.school_to_full(self.school)

    @property
    def level_text(self) -> str:
        """ "Cantrip" or "3rd-level"."""
        return normalize.level_to_level_text(self.level)

    @property
    def subtitle(self) -> str:
        """The statblock subtitle: "3rd-level evocation"."""
        return normalize.level_school_to_full(self.level, self.school)

    @property
    def casting_time(self) -> str:
        return normalize.time_to_full(self.time)

    @property
    def range_text(self) -> str:
        return normalize.range_to_full(self.range)

    @property
    def components_text(self) -> str:
        return normalize.components_to_full(self.components, self.level)

    @property
    def duration_text(self) -> str:
        """May contain {@status Concentration} markup, as upstream's does."""
        return normalize.duration_to_full(self.duration)

    @property
    def is_concentration(self) -> bool:
        """Concentration is a property of a duration entry, not of the spell."""
        return normalize.is_concentration(self.duration)

    @property
    def is_ritual(self) -> bool:
        """Ritual lives at meta.ritual, not at the top level."""
        return bool((self.meta or {}).get("ritual"))

    @property
    def uid(self) -> str:
        """The upstream-style identifier: "fireball|xphb"."""
        return f"{self.name.lower()}|{self.source.lower()}"
