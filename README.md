# 5et

A CLI for looking up D&D 5e spells from [5etools](https://5e.tools) data and exporting them as markdown.

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the layout and [docs/DESIGN.md](docs/DESIGN.md) for the design and the reasoning behind it.

## Install

```sh
uv sync
```

This provides two equivalent entry points, `5et` and `fivetools`.

## Quick start

```sh
uv run 5et sync            # fetch and index spell data, required once
uv run 5et spell fireball  # pretty terminal output
```

## Usage

```
5et sync [--version TAG] [--force] [--format {auto,text,json}]
5et spell NAME [--source SRC] [--2014 | --2024] [--format {auto,rich,md,json}]
               [--template NAME] [--links {wikilink,plain,url}] [--output DIR] [--force]
5et search [QUERY] [--level N] [--school NAME] [--class NAME] [--source SRC]
               [--2014 | --2024] [--limit N] [--format {auto,rich,text,json}]
5et sources [--format {auto,rich,text,json}]
5et cache info [--format {auto,text,json}]
5et cache clear [--yes] [--format {auto,text,json}]
```

### Looking things up

Names resolve by exact match, then prefix, then fuzzy, so typos work. When a guess is involved it says so on stderr.

```sh
5et spell firebal                 # resolves to Fireball, notes the match on stderr
5et spell fireball --source PHB   # the 2014 version rather than the 2024 one
5et search ward --level 2
5et search --class Druid --level 0
```

A spell that exists in both the 2014 and 2024 books is ambiguous. The 2024 source wins by default, and the choice is reported on stderr. Set `source_priority` in the config to change that, or pass `--source`.

### Playing one edition

`--2014` and `--2024` scope a lookup or a search to one rules edition, which is usually what you want when a table is playing one of them.

```sh
5et spell fireball --2014         # the Player's Handbook version
5et search --class Wizard --2024  # the 2024 wizard list
```

The two Player's Handbooks are the only books that cover the same ground twice, so an edition excludes the other edition's handbook rather than restricting you to a single book: `--2014` keeps PHB and every supplement, `--2024` keeps XPHB and every supplement. Spells from Xanathar's, Tasha's and the rest stay available either way.

A spell printed only in the excluded handbook is reported as no match, naming the edition. The flags cannot be combined with each other, or with a `--source` the edition rules out.

### Exporting markdown

Rich output appears only when stdout is a terminal, so redirecting gives clean markdown with no flag:

```sh
5et spell fireball > Fireball.md
5et spell fireball -o ~/vault/Spells          # writes <Name>.md, refuses to clobber
5et spell fireball -t compact --links plain
5et spell fireball --format md | less         # force markdown on a terminal
```

Three templates ship: `obsidian` (YAML frontmatter, wikilinks), `plain` (a readable statblock) and `compact` (two header lines plus prose). Drop your own `<name>.md.j2` into the config `templates/` directory to add one or shadow a shipped one. Templates receive a flat, pre-rendered context, documented in [docs/DESIGN.md](docs/DESIGN.md) section 10.

### JSON

Every command takes `--format json`, which is the normalized view this tool works in rather than the raw 5etools record: levels and schools spelled out, concentration and ritual as booleans, no `{@damage 8d6}` markup left in any value.

```sh
5et spell fireball --format json | jq .range
5et search --class Wizard --level 3 --format json | jq -r '.results[].name'
5et cache info --format json | jq .version
```

Each payload is a single object, every documented key is always present (`null` when it does not apply), and an empty search is `{"count": 0, "results": []}` rather than an error. Notes and prompts stay on stderr, so stdout parses on its own.

`description` and `higher_levels` carry markdown prose, since the upstream spell body is nested prose with tables in it. They follow `--links` like markdown does, so `--format json --links plain` gives text with no wikilink syntax.

If you want the upstream records themselves, read them out of the cache directory that `5et cache info` prints; `--format json` is a stable surface for this tool, not a passthrough.

## Configuration

Optional TOML at `<config dir>/config.toml`, which is `~/.config/5et/config.toml` on Linux:

```toml
links = "wikilink"                  # wikilink | plain | url
template = "obsidian"
source_priority = ["XPHB", "PHB"]   # which book wins on a name collision
fuzzy_cutoff = 80
output_dir = "~/vault/Spells"
```

`FIVET_CACHE_DIR` and `FIVET_CONFIG_DIR` override the respective locations.

## Data and licensing

No game data is distributed with this tool. `5et sync` fetches JSON from the [5etools-src](https://github.com/5etools-mirror-3/5etools-src) repository at a pinned release tag into a local per-user cache, and records the version so exported markdown can cite it. That data is Wizards of the Coast content and is not redistributed here.

Pin a specific upstream release with `5et sync --version v2.39.0`. Without it, sync pins whatever is newest at that moment and does not drift afterward.

## Development

```sh
uv run pytest            # unit, snapshot and CLI tests, fully offline
uv run ruff check .
uv run ruff format .
```

Snapshot tests use hand-written fixtures mirroring real spell structures; regenerate with `uv run pytest --snapshot-update`.

An extra suite checks invariants against real synced data, and skips unless a cache exists:

```sh
uv run 5et sync && uv run pytest tests/test_integration.py
```
