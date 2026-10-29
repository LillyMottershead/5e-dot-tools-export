# Architecture

Where things live and what depends on what. For the reasoning behind these choices, see [DESIGN.md](DESIGN.md).

## Repository

```
.
├── AGENTS.md                      orientation for coding agents
├── README.md                      user-facing usage
├── pyproject.toml                 deps, console scripts, ruff and pytest config
├── docs/
│   ├── ARCHITECTURE.md            this file
│   └── DESIGN.md                  design, rationale, upstream data facts
├── examples/
│   └── config.toml                annotated sample user config
├── src/fivet/                     the package
└── tests/                         the suite
```

## Package

```
src/fivet/
├── __init__.py                    version only
├── cli.py                         click commands; parsing and output routing, no logic
├── config.py                      Settings model, TOML load, XDG paths, source ranking
├── models.py                      Spell: lax pydantic model plus derived display properties
├── normalize.py                   closed enumerations: school, level, time, range, components, duration
├── store.py                       SQLite + FTS5 index, name resolution, filtered search
├── sync.py                        version resolution, fetch, cache write, manifest, class join
├── render/
│   ├── tags.py                    {@tag} markup to markdown; depth-aware splitters; LinkStyle
│   ├── entries.py                 recursive entries tree to markdown blocks
│   ├── markdown.py                template context assembly, Jinja2 render, YAML quoting
│   └── terminal.py                rich panel, search and source tables
└── templates/
    ├── obsidian.md.j2             YAML frontmatter plus body, wikilinks
    ├── plain.md.j2                readable statblock
    └── compact.md.j2              two header lines plus prose
```

### Dependency direction

Imports flow one way, so the risky parts are testable in isolation:

```
normalize ──→ models ──→ store ──→ sync
    │            │          ↑        │
    │            ↓          │        │
tags ──→ entries ──→ markdown       │
  │                     ↑            │
  │                  config ─────────┘
  └──→ terminal           │
            └─────────────┴──→ cli
```

`tags.py` and `normalize.py` import nothing internal. `cli.py` is imported by nothing. The markup layer (`tags`, `entries`) needs no network, no cache and no CLI to test, which is the point of the split: it is the part most likely to regress.

## Cache layout

Created by `5et sync` at `platformdirs.user_cache_dir("5et")`, overridable with `FIVET_CACHE_DIR`:

```
<cache>/
├── manifest.json                  pinned tag, fetch timestamp, sha256 per file
├── index.db                       SQLite; built to .db.tmp then moved into place
└── raw/
    ├── index.json                 source abbreviation to filename
    ├── spells-<src>.json          one per source book, 18 of them
    └── sources.json               class availability reverse index
```

No game data is committed to this repository. See DESIGN.md section 2.

## Config layout

At `platformdirs.user_config_dir("5et")`, overridable with `FIVET_CONFIG_DIR`:

```
<config>/
├── config.toml                    optional; see examples/config.toml
└── templates/
    └── <name>.md.j2               user templates, shadowing shipped ones by name
```

## Tests

```
tests/
├── conftest.py                    isolated_dirs, raw_spell, raw_cantrip, spell_set, store
├── test_normalize.py              exhaustive over each enumeration
├── test_tags.py                   per tag group, nesting, unknown-tag fallback
├── test_entries.py                each entry type, table escaping
├── test_models.py                 parsing, laxness, derived properties
├── test_config.py                 loading, validation, source ranking
├── test_store.py                  build, resolution, ambiguity, search, FTS safety
├── test_sync.py                   fetch and cache, all HTTP mocked with respx
├── test_markdown.py               context, YAML quoting, templates
├── test_terminal.py               rich output content
├── test_cli.py                    every command, via click's CliRunner
├── test_snapshots.py              19 snapshots over hand-written fixtures
├── test_integration.py            invariants against real data; skips without a cache
└── __snapshots__/
    └── test_snapshots.ambr        committed snapshot output
```
