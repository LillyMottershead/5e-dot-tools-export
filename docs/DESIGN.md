# 5et: a CLI for 5etools spell data

Status: implemented
Last updated: 2026-10-28
Data surveyed against 5etools-src `v2.39.0` (released 2026-10-24)

## 1. Goal and scope

A Python CLI that looks up a D&D 5e spell by name and converts it to markdown, offline, with reproducible output.

In scope for v1:

- `5et sync`: fetch and index spell data from a pinned upstream version
- `5et spell <name>`: render one spell to the terminal or to markdown
- `5et search <query>`: filter by name, level, school, class, source
- Markdown export through user-overridable Jinja2 templates

Explicitly out of scope for v1, but the architecture should not foreclose it: monsters, items, classes, feats. The bestiary is roughly 40 MB against the spell corpus's 1.5 MB, which is the main reason for the storage decision in section 4.

Non-goal: reimplementing `js/render.js`. Section 6 bounds exactly how much of the markup layer v1 covers.

## 2. Why build on the source repo

5e.tools has no documented public API. The site is a static client-side app that reads JSON files shipped alongside it, so those JSON files are the de facto interface and they are the most stable thing available. Community API wrappers add a dependency on someone else's uptime and parsing choices for no gain, because the parsing is the part we actually need to control.

The upstream repo is `5etools-mirror-3/5etools-src`. It cuts tagged releases roughly weekly, each with a single zip asset. Tags are what we pin to, so a given cache is a snapshot of a known upstream version and exported markdown can cite it.

### Licensing

The 5etools code is MIT. The game data it ships is Wizards of the Coast content and is not ours to redistribute. Consequences for this project:

- No data is vendored into this repository, ever. Not even test fixtures copied wholesale.
- Data is fetched at runtime into a per-user cache directory.
- Test fixtures are small hand-written records that exercise schema shapes, not copies of real spell text.

## 3. Data layer, as confirmed upstream

Spells live in `data/spells/`:

| File | Role |
| --- | --- |
| `index.json` | source abbreviation to filename, 18 entries |
| `spells-<src>.json` | `{"spell": [...]}`, one array per source book |
| `sources.json` | class availability reverse index, 244 KB |
| `fluff-spells-<src>.json` | flavor text and image references, not used in v1 |

Total fetch for v1 is about 1.5 MB across 20 requests.

### 3.1 Spell record

Confirmed by reading `Fireball` from `spells-xphb.json`:

```json
{
  "name": "Fireball",
  "source": "XPHB",
  "page": 274,
  "level": 3,
  "school": "V",
  "time": [{"number": 1, "unit": "action"}],
  "range": {"type": "point", "distance": {"type": "feet", "amount": 150}},
  "components": {"v": true, "s": true, "m": "a ball of bat guano and sulfur"},
  "duration": [{"type": "instant"}],
  "entries": ["A bright streak flashes ... {@damage 8d6} Fire damage ..."],
  "entriesHigherLevel": [{"type": "entries", "name": "Using a Higher-Level Spell Slot", "entries": ["..."]}],
  "damageInflict": ["fire"],
  "savingThrow": ["dexterity"],
  "areaTags": ["S"]
}
```

### 3.2 Field normalization rules

Upstream's formatters take a `styleHint` of `classic` (2014 phrasing: `1 action`, `3rd-level evocation`) or `one` (2024 phrasing: `Action`, `Level 3 Evocation`). v1 always formats in `classic` style, including for 2024-source spells, so that exported markdown reads consistently across editions. If that turns out to be the wrong call it becomes a config key alongside `links`.

Every variant below is the complete observed set across 935 spells from the seven largest sources (PHB, XPHB, XGE, TCE, EGW, AU, FRHoF). These are closed sets in practice, so normalization is table-driven, not heuristic.

School is a single letter. All eight occur: `A` Abjuration, `C` Conjuration, `D` Divination, `E` Enchantment, `I` Illusion, `N` Necromancy, `T` Transmutation, `V` Evocation. A `P` (psionic) code exists upstream but appears in no spell file.

Casting time is a list of `{number, unit}`. Units observed: `action`, `bonus`, `reaction`, `minute`, `hour`. A `reaction` entry carries a `condition` string that must be appended, for example `1 reaction, which you take in response to taking damage`.

Range is `{type, distance}` with 16 observed combinations. `type: "point"` is the ordinary case and renders from `distance.type`, which is one of `feet`, `miles`, `touch`, `self`, `sight`, `unlimited`. A non-point `type` is an area of effect and renders as `Self (20-foot Emanation)` style: observed types are `emanation`, `radius`, `cone`, `line`, `sphere`, `cube`, `hemisphere`, plus one bare `special`.

Duration is a list of `{type, duration, concentration, ends}`. `type` is `timed`, `instant`, `permanent`, or `special`. For `timed`, `duration` is `{type, amount}` where type is one of `round`, `minute`, `hour`, `day`. Concentration is a boolean on the duration entry, not a top-level field, which matters because the obvious place to look for it is wrong. `permanent` carries `ends`, a list such as `["dispel"]`.

Ritual is at `meta.ritual`, not top level. 67 of 935 spells have it.

### 3.3 Class availability

`sources.json` is keyed by source abbreviation, then by spell name:

```json
{"XPHB": {"Fireball": {"class": [{"name": "Sorcerer", "source": "XPHB"}, {"name": "Wizard", "source": "XPHB"}]}}}
```

Per-spell keys are only `class` (834 spells) and `classVariant` (180). This confirms the `classes` frontmatter field is viable. v1 reads `class` only and ignores `classVariant`, which covers optional-feature grants such as Artificer infusions and would need its own presentation to be meaningful.

Note the join key is the pair `(source, name)`, not name alone, because a 2014 and 2024 spell of the same name can have different class lists.

## 4. Architecture

Four layers. The point of the split is that the markup converter, which is the part most likely to regress, is testable with no network, no cache, and no CLI.

The file layout and the dependency direction are in [ARCHITECTURE.md](ARCHITECTURE.md), which is the authoritative map. This section covers only the reasoning.

### 4.1 Cache and storage

Cache lives at `platformdirs.user_cache_dir("5et")`:

```
<cache>/
  manifest.json       pinned tag, fetch timestamp, per-file sha256
  raw/                the JSON exactly as fetched
  index.db            SQLite
```

Decision: build a SQLite index at sync time rather than parsing JSON on every invocation.

For 2000 spells, loading JSON into memory each run would be fine. The reason to use SQLite anyway is that the bestiary is 40 MB, and a tool that parses 40 MB before printing one monster is a tool nobody uses twice. The schema is entity-agnostic from day one so adding monsters is a sync change, not an architecture change:

```sql
CREATE TABLE entity (
  id INTEGER PRIMARY KEY,
  kind TEXT NOT NULL,          -- 'spell', later 'monster', 'item'
  name TEXT NOT NULL,
  source TEXT NOT NULL,
  level INTEGER,
  school TEXT,
  json TEXT NOT NULL,          -- the record, verbatim
  UNIQUE (kind, name, source)
);
CREATE INDEX entity_lookup ON entity (kind, name COLLATE NOCASE);
CREATE TABLE entity_class (entity_id INTEGER, class_name TEXT);
CREATE VIRTUAL TABLE entity_fts USING fts5 (name, content='entity', content_rowid='id');
```

Storing the record verbatim rather than exploding it into columns means a schema change upstream cannot corrupt the index. Columns exist only for the fields we filter on. Everything else is read back out of `json` and into the pydantic model.

`sqlite3` and FTS5 are stdlib, so this adds no dependency.

### 4.2 Sync

1. `GET /repos/5etools-mirror-3/5etools-src/releases/latest`, read `tag_name`. If `--version` was passed, use it and skip this.
2. Fetch `data/spells/index.json` at that tag from `raw.githubusercontent.com`.
3. Fetch each `spells-<src>.json` listed, plus `sources.json`.
4. Write to `raw/`, record sha256 of each file in `manifest.json`.
5. Rebuild `index.db` in a temp file, then atomically rename over the old one, so an interrupted sync leaves the previous index intact.

Chose raw file fetch over the release zip because the zip is 49.6 MB of which about 48 MB is JavaScript, CSS and fonts. Chose it over a sparse git clone because that requires git on PATH and leaves a working tree in the cache. Both rejected options stay viable if the fetch count ever becomes a problem.

A sync is never implicit. If a lookup finds no cache it prints a message naming the sync command and exits 1. Downloading several megabytes as a side effect of a lookup is a surprise, and surprises in a tool you reach for reflexively are worse than one extra command on first run.

### 4.3 Data model

Lax pydantic v2: every field Optional, `model_config = ConfigDict(extra="allow")`, and only the fields actually rendered are declared.

The reasoning is that strict modeling of all 18 sources would fail on sync regularly, because the data has genuine inconsistencies across a decade of books, and a tool that breaks on upstream's weekly release is worse than one that silently ignores a field it does not use. Lax modeling still gives validation and editor completion over the fields that matter. Unknown additions pass through.

## 5. Resolution rules

### 5.1 Name to spell

1. Case-insensitive exact match on name.
2. If none, FTS5 prefix match.
3. If still none, `rapidfuzz` over all names, best match above a configurable cutoff, default 80.

A fuzzy or prefix hit prints what it resolved to on stderr, so `5et spell firebal` tells you it gave you Fireball without polluting stdout.

### 5.2 Source ambiguity

Fireball exists in both PHB (2014) and XPHB (2024). Both are real answers.

Resolution is a configured priority list, default `["XPHB", "PHB", "XGE", "TCE", ...]`, overridable per invocation with `--source XPHB`. When a name matches multiple sources, the highest-priority match wins and the pick is noted on stderr.

Rejected: interactive prompting, because it breaks piping to a file, which is the primary export path. Rejected: rendering all matches, because the common case is one spell and the noise is not worth it.

### 5.3 Edition scope

`--2014` and `--2024` scope a lookup or a search to one rules edition, for the common case of a table that plays one of them and does not want the other's wording.

An edition is expressed as an exclusion, not a restriction. Of the 18 sources carrying spells, PHB and XPHB are the only pair covering the same ground in both editions; the other 16 are supplements that belong to one edition or are edition-neutral, and a table on either edition still casts the spells printed in Xanathar's or Tasha's. So `--2014` means every source except XPHB and `--2024` means every source except PHB. Restricting to the handbook alone would hide 222 of the 583 distinct spell names under `--2014` and 192 under `--2024`, for no gain.

The scope applies to the whole candidate pool rather than to the final pick: exact, prefix and fuzzy matching all run against the scoped name set. Filtering only at the end would let a fuzzy search land on a name printed solely in the excluded handbook and then resolve to nothing, reporting a typo where the real answer is that the spell is not in that edition. Measured against the real corpus, a scope costs 13 names under `--2014` and 2 under `--2024`, and no name available in a supplement is ever lost.

Interaction with the priority list in 5.2 needs no special case: with XPHB excluded, the default `["XPHB", "PHB", ...]` ranking picks PHB by itself. `--source` naming the excluded handbook is a contradiction, so the CLI rejects it rather than reporting an empty result that hides the cause.

## 6. The markup layer

This is the part with real risk, so it gets a measured scope. Across the 935 surveyed spells there are exactly 26 distinct `{@tag}` types and 6 entry types. Counts below are occurrences, and they justify where the care goes.

### 6.1 Tag groups

Inline formatting, 56 uses: `@b`, `@i`, `@note`. Direct markdown equivalents.

Dice and numbers, 770 uses: `@damage`, `@dice`, `@dc`, `@hit`, `@d20`. Take the first pipe-delimited argument and emit it as text. `{@damage 8d6}` becomes `8d6`.

Scaling, 156 uses: `@scaledamage`, `@scaledice`. Argument form is `base|levelRange|step`, as in `8d6|3-9|1d6`. Upstream renders the step, not the base, because the surrounding sentence is always about the per-level increase: "The damage increases by 1d6 for each spell slot level above 3". Emitting the base here would overstate the scaling eightfold.

Cross-references, 1600+ uses and the group that must be correct: `@variantrule`, `@condition`, `@spell`, `@creature`, `@action`, `@skill`, `@status`, `@sense`, `@item`, `@hazard`, `@race`, `@classFeature`. Argument form is `name|source|displayText`. Upstream's rule is `parts[2] if len(parts) >= 3 else parts[0]`, so display text wins when present. When it is absent we additionally strip any trailing bracketed qualifier from the name, so a bare `{@variantrule Sphere [Area of Effect]|XPHB}` could not render as `Sphere [Area of Effect]`. No such case exists in the current data, checked across all 935 spells, so this is a safety net rather than a fix. Output form depends on the link setting in section 7.

Awkward but degradable, 96 uses: `@filter`, `@quickref`, `@book`, `@chance`. These carry site-specific navigation payloads, but in every observed case the first argument is already the human-readable text:

- `{@filter any beast|bestiary|type=beast|miscellaneous=!swarm}` to `any beast`
- `{@quickref difficult terrain||3}` to `difficult terrain`
- `{@chance 25|||Random reading!|Regular reading}` to `25 percent chance`

These render as plain text regardless of link setting, since there is no stable target to link to.

In `url` mode a cross-reference becomes a link only when its tag maps to a 5e.tools page and the tag carries an explicit source, since the URL hash is `name_source` and a guessed source produces a link that silently 404s. Everything else degrades to plain text.

Any tag not in the dispatch table falls back to emitting its first argument and logging at debug level. An unknown tag should degrade to readable prose, never to a traceback or a literal `{@...}` in someone's vault.

### 6.2 Entry types

`entries` (563) nests, with an optional `name` that becomes a heading or a bold lead-in depending on depth. `list` (52) and its `item` children become `-` bullets. `table` (27) becomes a GFM table; `colLabels` can themselves contain tags, and `cell` objects carry `roll.exact` or a min/max range rather than a plain value. `inset` (1) becomes a blockquote.

One recursive function over these six types, roughly 80 lines.

## 7. Configuration

TOML at `<user_config_dir>/5et/config.toml`, read with stdlib `tomllib`, validated by the pydantic already in the dependency list. No extra package.

```toml
links = "wikilink"                      # wikilink | plain | url
source_priority = ["XPHB", "PHB"]
template = "obsidian"
fuzzy_cutoff = 80
output_dir = "~/vault/Spells"
```

`links` controls cross-reference rendering: `wikilink` gives `[[burning]]`, `plain` gives `burning`, `url` gives a markdown link to the 5e.tools page. Default is `wikilink` because markdown export usually means a vault. Overridable per run with `--links`.

## 8. CLI surface

```
5et sync [--version TAG] [--force] [--format {auto,text,json}]
5et spell NAME [--source SRC] [--2014 | --2024] [--format {auto,rich,md,json}]
              [--template NAME] [--links {wikilink,plain,url}] [--output DIR] [--force]
5et search QUERY [--level N] [--school NAME] [--class NAME] [--source SRC] [--2014 | --2024]
              [--limit N] [--format {auto,rich,text,json}]
5et sources [--format {auto,rich,text,json}]
5et cache info [--format {auto,text,json}]
5et cache clear [--yes] [--format {auto,text,json}]
```

Behaviors:

- `--format` defaults to `auto`: rich only when stdout is a TTY, so `5et spell fireball > f.md` yields clean markdown with no flag. `--output` also implies markdown. Every command takes it, with the same four names meaning the same four things throughout: `auto`, `rich`, the command's plain text shape (`md` for one spell, tab-separated lines for a listing or a report) and `json`
- `rich` is not offered by `sync` or `cache`, which report rather than present; there is no panel or table for them to produce
- advisory notes (a fuzzy match, a source ambiguity) go to stderr, so redirected markdown stays clean
- `--2014` and `--2024` scope to one rules edition per section 5.3; they are mutually exclusive, and `sources` deliberately does not take them, since a cache inventory should report what was actually fetched
- `--output DIR` writes `Fireball.md` and refuses to overwrite without `--force`
- `--version` on sync pins; without it, sync pins whatever is newest at that moment and never drifts afterward
- command is `5et`, with `fivetools` as a second console script for anyone who dislikes a leading digit

### 8.1 JSON output

`--format json` emits the normalized display view, never the raw upstream record. The shapes are built in `render/payloads.py` and are the same values the templates and the terminal panel consume: `level_text` rather than a bare `level`, `school` spelled out, `concentration` and `ritual` as booleans lifted out of `duration` and `meta`, and markup stripped from every scalar.

This is a deliberate cost. Passing the record through would be one line and would give a consumer more fields, but it would also make every upstream schema change a breaking change for anyone parsing our output, and it would hand them `{@damage 8d6}` to deal with. Anyone who wants the raw record can read `raw/spells-<src>.json` out of the cache, which is exactly what it is for.

Rules that hold for every command:

- the payload is a JSON object, never a bare array, so a later version can add a key without breaking a consumer
- every documented key is always present; `null` means not applicable, not omitted. `cache info` on an empty cache reports `"cached": false` with the rest nulled rather than a short object
- an empty result is a result: `search` with no matches prints `{"count": 0, "results": [], ...}` and exits 0
- notes, prompts and progress stay on stderr, so stdout is parseable on its own. This is why `cache clear` asks for confirmation on stderr
- `data_version` travels with any payload read out of the index, so an export can cite the upstream release it came from

Two fields are prose rather than structure: `description` and `higher_levels` carry rendered markdown, because the upstream entries tree is nested prose with tables and inline rolls, and there is no faithful JSON for it short of republishing the tree. They honor `--links` and the configured link style like any other prose, so `--format json --links plain` gives text with no wikilink syntax in it.

## 9. Dependencies

| Package | Role |
| --- | --- |
| click | CLI framework |
| httpx | fetching, sane timeouts, redirect handling |
| platformdirs | correct cache and config paths per platform |
| rich | terminal rendering |
| rapidfuzz | fuzzy name matching, C++ core, no transitive deps |
| jinja2 | markdown templates |
| pydantic v2 | spell model and config validation |

Dev: pytest, syrupy, ruff.

Deliberately not used: `orjson`, because stdlib json parses the whole spell corpus in about 20 ms and it happens once per sync, not per lookup. `requests`, superseded by httpx. `typer`, since click was specified. `questionary`, since section 5.2 chose non-interactive resolution. `sqlalchemy`, since the schema is one table and two indexes.

## 10. Template contract

Templates receive a flat, pre-rendered context so that writing one requires no knowledge of the 5etools schema:

```python
{
    "name": "Fireball",
    "level": 3,
    "level_text": "3rd-level",
    "school": "Evocation",
    "casting_time": "1 action",
    "range": "150 feet",
    "components": "V, S, M (a ball of bat guano and sulfur)",
    "duration": "Instantaneous",
    "concentration": False,
    "ritual": False,
    "classes": ["Sorcerer", "Wizard"],
    "source": "XPHB",
    "page": 274,
    "description_md": "...",  # already converted
    "higher_levels_md": "...",  # already converted, or None
    "data_version": "v2.39.0",
}
```

All markup conversion happens before the template sees anything. Templates do layout, never parsing.

Shipped: `obsidian.md.j2`, `plain.md.j2`, `compact.md.j2`. User templates in `<user_config_dir>/5et/templates/` are discovered by name and shadow shipped ones.

Target output for `5et spell fireball -t obsidian`:

```markdown
---
title: Fireball
level: 3
school: Evocation
casting_time: 1 action
range: 150 feet
components: V, S, M (a ball of bat guano and sulfur)
duration: Instantaneous
concentration: false
ritual: false
classes: [Sorcerer, Wizard]
source: XPHB p.274
data_version: v2.39.0
tags: [spell/level/3, spell/school/evocation]
---

# Fireball

3rd-level Evocation

A bright streak flashes from you to a point you choose within range and then blossoms with a low roar into a fiery explosion. Each creature in a 20-foot-radius [[Sphere]] centered on that point makes a Dexterity saving throw, taking 8d6 Fire damage on a failed save or half as much damage on a successful one.

Flammable objects in the area that aren't being worn or carried start [[burning]].

## Using a Higher-Level Spell Slot

The damage increases by 8d6 for each spell slot level above 3.
```

## 11. Testing

The renderer is where regressions hide, and upstream ships weekly, so the test strategy is built around making a data bump a reviewable diff.

Snapshot tests via syrupy over a fixed set of about 20 spells chosen for coverage rather than popularity: every tag group, every entry type, every field variant from section 3.2. Named cases include Fireball (baseline, scaling), Chaos Bolt (table with `roll.exact` cells), a reaction spell (time `condition`), an emanation spell (non-point range), a permanent spell (`ends`), a ritual spell (`meta.ritual`), and whichever spells carry the `@filter` and `@chance` oddities.

Unit tests on `normalize.py` cover the section 3.2 tables directly, since those are closed enumerations and can be tested exhaustively.

Tag handler tests use hand-written strings, not real spell text, which keeps section 2's licensing constraint intact.

A guard test asserts that an unknown `{@tag}` degrades to its first argument rather than raising.

## 12. Open questions

- Whether `classVariant` from `sources.json` deserves presentation in a later version, and if so how to distinguish it from baseline class access. v1 reads only `class` (834 of 969 spells); `classVariant` covers a further 180 and would need its own presentation to be meaningful.
- Whether fluff files are worth pulling for flavor text, which would roughly double fetch size for content most templates would not use.
- Whether formatting should follow the 2024 style hint for 2024-source spells instead of always using `classic` (section 3.2). This becomes a config key if the current choice reads wrong in practice.

## 13. Divergences from the original design

Recorded so the reasoning is not lost. Each was driven by reading upstream or by a failing test, not by preference.

`@scaledamage` renders the step, not the base. The original plan emitted the base, which would have overstated scaling eightfold in the one sentence it appears in. Corrected in section 6.1 after reading upstream's `_TagDiceFlavorScaling`.

Formatting fixed to the `classic` style hint. Upstream formats differently per edition; v1 picks one so exports read consistently. Noted in section 3.2 and listed above as still open.

Edition flags exclude a book rather than selecting one. The feature was first written down as "`--2014` and `--2024` filter to PHB or XPHB", which would have dropped every supplement from a scoped result and hidden roughly a third of the corpus. Implemented as the exclusion described in section 5.3 instead, since only the two handbooks are edition-specific.

`url` link mode is conditional. A link is produced only when the tag maps to a 5e.tools page and carries an explicit source, because the hash is `name_source` and a guessed source yields a link that silently 404s.

Only `name`, `source` and `level` are required on the model, rather than all ten universal fields. Requiring the other seven would turn an upstream schema tweak into a failed sync for no benefit.

Frontmatter values are plain text while body prose carries the link style, and both are YAML-quoted on demand. A rendered wikilink begins with `[`, which YAML would read as a flow sequence; and writing that test surfaced a second case, where a comma is harmless in a block scalar but separates items inside a flow sequence, so class lists need stricter quoting than plain values.

The template context carries `higher_levels_inline` alongside `higher_levels_md`, the same content with its heading folded into a bold lead-in, for templates such as `compact` where an h2 would be out of place.

Snapshot tests use hand-written fixtures that mirror the structure of named real spells, rather than the real spells themselves, to respect the licensing constraint in section 2. Invariant checks against real data live in an opt-in test module that skips unless a cache exists.

`--format` is one flag with per-command choices, rather than a `--json` switch per command. The alternative reads shorter at the call site but makes `auto` unexpressible, and the TTY fallback is the behavior that most wants naming: `--format md` and `--format text` exist so a plain shape can be forced while attached to a terminal, which was previously impossible for `search` and `sources`.

`--format rich --output DIR` is a usage error. It used to print a panel and silently ignore `--output`, writing nothing; a file is never a terminal, so the combination has no meaning worth guessing at.
