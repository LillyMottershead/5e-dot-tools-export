"""The SQLite index over cached entity data.

Design notes from docs/DESIGN.md section 4.1: records are stored verbatim as
JSON, and columns exist only for the fields we filter on, so an upstream schema
change cannot corrupt the index. The schema is entity-agnostic from the start
because the bestiary is roughly 40 MB against the spell corpus's 1.5 MB, and a
tool that parses 40 MB before printing one monster is one nobody uses twice.

`sqlite3` and FTS5 are stdlib, so this costs no dependency.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from rapidfuzz import fuzz, process

from fivet.config import Edition, Settings
from fivet.models import Spell
from fivet.normalize import SCHOOLS

KIND_SPELL = "spell"

SCHEMA = """
CREATE TABLE entity (
  id      INTEGER PRIMARY KEY,
  kind    TEXT NOT NULL,
  name    TEXT NOT NULL,
  source  TEXT NOT NULL,
  level   INTEGER,
  school  TEXT,
  json    TEXT NOT NULL,
  UNIQUE (kind, name, source)
);
CREATE INDEX entity_lookup ON entity (kind, name COLLATE NOCASE);
CREATE TABLE entity_class (
  entity_id  INTEGER NOT NULL REFERENCES entity(id) ON DELETE CASCADE,
  class_name TEXT NOT NULL
);
CREATE INDEX entity_class_lookup ON entity_class (class_name COLLATE NOCASE);
CREATE VIRTUAL TABLE entity_fts USING fts5 (
  name,
  content='entity',
  content_rowid='id'
);
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""

_WORD = re.compile(r"\w+", re.UNICODE)


class MatchKind(StrEnum):
    """How a name resolved, so the CLI can say when it guessed."""

    EXACT = "exact"
    PREFIX = "prefix"
    FUZZY = "fuzzy"


@dataclass
class Match:
    """A resolved spell, plus the same-named spells from other books."""

    spell: Spell
    kind: MatchKind
    alternatives: list[Spell]

    @property
    def is_ambiguous(self) -> bool:
        return bool(self.alternatives)


class StoreMissingError(RuntimeError):
    """Raised when no index exists, so the CLI can point at `5et sync`."""


def _fts_query(text: str) -> str:
    """Build a safe FTS5 prefix query.

    User input goes nowhere near FTS5 syntax: tokens are extracted and quoted,
    so characters like parentheses or quotes cannot produce a syntax error.
    """
    tokens = _WORD.findall(text)
    if not tokens:
        return ""
    return " AND ".join(f'"{token}"*' for token in tokens)


def _edition_filter(edition: Edition | None, column: str = "source") -> tuple[str, list[Any]]:
    """SQL fragment and params scoping a query to one rules edition.

    An edition excludes the other edition's Player's Handbook rather than
    selecting a single source; see `config.Edition`.
    """
    if edition is None:
        return "", []
    return f" AND {column} <> ? COLLATE NOCASE", [edition.excluded_source]


def _normalize_school(value: str) -> str | None:
    """Accept either a school code or its full name, case-insensitively."""
    if not value:
        return None
    if len(value) == 1 and value.upper() in SCHOOLS:
        return value.upper()
    wanted = value.strip().lower()
    for code, full in SCHOOLS.items():
        if full.lower() == wanted:
            return code
    return None


class Store:
    """Read and write access to the index."""

    def __init__(self, path: Path):
        self.path = path
        self._connection: sqlite3.Connection | None = None

    # -- lifecycle ---------------------------------------------------------

    @property
    def connection(self) -> sqlite3.Connection:
        if self._connection is None:
            if not self.path.is_file():
                raise StoreMissingError(f"No index at {self.path}")
            self._connection = sqlite3.connect(f"file:{self.path}?mode=ro", uri=True)
            self._connection.row_factory = sqlite3.Row
        return self._connection

    def close(self) -> None:
        if self._connection is not None:
            self._connection.close()
            self._connection = None

    def __enter__(self) -> Store:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    @classmethod
    def build(
        cls,
        path: Path,
        spells: Iterable[Spell],
        meta: dict[str, str] | None = None,
    ) -> Store:
        """Build the index into a temp file, then move it into place.

        The move is atomic, so an interrupted build leaves the previous index
        usable rather than truncated.
        """
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = path.with_suffix(".db.tmp")
        temp_path.unlink(missing_ok=True)

        connection = sqlite3.connect(temp_path)
        try:
            connection.executescript(SCHEMA)
            for spell in spells:
                cursor = connection.execute(
                    "INSERT OR REPLACE INTO entity (kind, name, source, level, school, json) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        KIND_SPELL,
                        spell.name,
                        spell.source,
                        spell.level,
                        spell.school,
                        spell.model_dump_json(by_alias=True),
                    ),
                )
                if spell.classes:
                    connection.executemany(
                        "INSERT INTO entity_class (entity_id, class_name) VALUES (?, ?)",
                        [(cursor.lastrowid, name) for name in spell.classes],
                    )
            connection.execute("INSERT INTO entity_fts (rowid, name) SELECT id, name FROM entity")
            for key, value in (meta or {}).items():
                connection.execute(
                    "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (key, value)
                )
            connection.commit()
        finally:
            connection.close()

        os.replace(temp_path, path)
        return cls(path)

    # -- reads -------------------------------------------------------------

    def _to_spell(self, row: sqlite3.Row) -> Spell:
        return Spell.model_validate(json.loads(row["json"]))

    def count(self, kind: str = KIND_SPELL) -> int:
        row = self.connection.execute(
            "SELECT COUNT(*) AS n FROM entity WHERE kind = ?", (kind,)
        ).fetchone()
        return row["n"]

    def meta(self) -> dict[str, str]:
        try:
            rows = self.connection.execute("SELECT key, value FROM meta").fetchall()
        except sqlite3.OperationalError:
            return {}
        return {row["key"]: row["value"] for row in rows}

    def sources(self, kind: str = KIND_SPELL) -> list[tuple[str, int]]:
        rows = self.connection.execute(
            "SELECT source, COUNT(*) AS n FROM entity WHERE kind = ? "
            "GROUP BY source ORDER BY n DESC, source",
            (kind,),
        ).fetchall()
        return [(row["source"], row["n"]) for row in rows]

    def names(self, kind: str = KIND_SPELL, edition: Edition | None = None) -> list[str]:
        clause, extra = _edition_filter(edition)
        rows = self.connection.execute(
            f"SELECT DISTINCT name FROM entity WHERE kind = ?{clause} ORDER BY name",
            (kind, *extra),
        ).fetchall()
        return [row["name"] for row in rows]

    def by_name(
        self, name: str, kind: str = KIND_SPELL, edition: Edition | None = None
    ) -> list[Spell]:
        """Every spell with this exact name, case-insensitively, across sources."""
        clause, extra = _edition_filter(edition)
        rows = self.connection.execute(
            f"SELECT json FROM entity WHERE kind = ? AND name = ? COLLATE NOCASE{clause}",
            (kind, name, *extra),
        ).fetchall()
        return [self._to_spell(row) for row in rows]

    def prefix_search(
        self,
        query: str,
        kind: str = KIND_SPELL,
        limit: int = 50,
        edition: Edition | None = None,
    ) -> list[Spell]:
        fts = _fts_query(query)
        if not fts:
            return []
        clause, extra = _edition_filter(edition, "e.source")
        rows = self.connection.execute(
            "SELECT e.json FROM entity_fts f JOIN entity e ON e.id = f.rowid "
            f"WHERE entity_fts MATCH ? AND e.kind = ?{clause} ORDER BY e.name LIMIT ?",
            (fts, kind, *extra, limit),
        ).fetchall()
        return [self._to_spell(row) for row in rows]

    def fuzzy_names(
        self,
        query: str,
        cutoff: int = 80,
        limit: int = 5,
        edition: Edition | None = None,
    ) -> list[tuple[str, float]]:
        matches = process.extract(
            query,
            self.names(edition=edition),
            scorer=fuzz.WRatio,
            score_cutoff=cutoff,
            limit=limit,
        )
        return [(name, score) for name, score, _ in matches]

    # -- resolution --------------------------------------------------------

    def resolve(
        self,
        name: str,
        settings: Settings | None = None,
        source: str | None = None,
        edition: Edition | None = None,
    ) -> Match | None:
        """Resolve a name to one spell, preferring exact over prefix over fuzzy.

        Source ambiguity is settled by the configured priority, never by a
        prompt, so output stays pipeable.

        An edition scopes every step, not just the final pick, so a prefix or
        fuzzy fallback cannot land on a name that exists only in the excluded
        book and then resolve to nothing.
        """
        settings = settings or Settings()

        candidates = self.by_name(name, edition=edition)
        kind = MatchKind.EXACT

        if not candidates:
            prefixed = self.prefix_search(name, limit=10, edition=edition)
            if prefixed:
                best = min(prefixed, key=lambda s: (len(s.name), s.name.lower()))
                candidates = self.by_name(best.name, edition=edition)
                kind = MatchKind.PREFIX

        if not candidates:
            fuzzy = self.fuzzy_names(name, cutoff=settings.fuzzy_cutoff, limit=1, edition=edition)
            if fuzzy:
                candidates = self.by_name(fuzzy[0][0], edition=edition)
                kind = MatchKind.FUZZY

        if not candidates:
            return None

        if source:
            wanted = source.upper()
            filtered = [s for s in candidates if s.source.upper() == wanted]
            if not filtered:
                return None
            candidates = filtered

        ordered = sorted(candidates, key=lambda s: settings.source_rank(s.source))
        return Match(spell=ordered[0], kind=kind, alternatives=ordered[1:])

    # -- search ------------------------------------------------------------

    def search(
        self,
        query: str | None = None,
        level: int | None = None,
        school: str | None = None,
        class_name: str | None = None,
        source: str | None = None,
        edition: Edition | None = None,
        kind: str = KIND_SPELL,
        limit: int = 200,
    ) -> list[Spell]:
        """Filtered listing. All supplied filters must match."""
        sql = ["SELECT DISTINCT e.json, e.name FROM entity e"]
        where = ["e.kind = ?"]
        params: list[Any] = [kind]

        if class_name:
            sql.append("JOIN entity_class c ON c.entity_id = e.id")
            where.append("c.class_name = ? COLLATE NOCASE")
            params.append(class_name)

        if query:
            fts = _fts_query(query)
            if not fts:
                return []
            sql.append("JOIN entity_fts f ON f.rowid = e.id")
            where.append("entity_fts MATCH ?")
            params.append(fts)

        if level is not None:
            where.append("e.level = ?")
            params.append(level)

        if school:
            code = _normalize_school(school)
            if code is None:
                return []
            where.append("e.school = ?")
            params.append(code)

        if source:
            where.append("e.source = ? COLLATE NOCASE")
            params.append(source)

        if edition is not None:
            where.append("e.source <> ? COLLATE NOCASE")
            params.append(edition.excluded_source)

        sql.append("WHERE " + " AND ".join(where))
        sql.append("ORDER BY e.name, e.source LIMIT ?")
        params.append(limit)

        rows = self.connection.execute(" ".join(sql), params).fetchall()
        return [self._to_spell(row) for row in rows]


def load_spells(
    raw_by_source: dict[str, list[dict[str, Any]]],
    classes_by_uid: dict[tuple[str, str], Sequence[str]] | None = None,
) -> list[Spell]:
    """Build Spell models, attaching class availability from sources.json.

    The join key is the (source, name) pair rather than the name alone, because
    the 2014 and 2024 versions of a spell can list different classes.
    """
    classes_by_uid = classes_by_uid or {}
    spells = []
    for source, records in raw_by_source.items():
        for record in records:
            spell = Spell.model_validate(record)
            key = (source.upper(), spell.name.lower())
            spell.classes = list(classes_by_uid.get(key, ()))
            spells.append(spell)
    return spells
