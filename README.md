# 5et

A CLI for looking up D&D 5e spells from [5etools](https://5e.tools) data and exporting them as markdown.

See [docs/DESIGN.md](docs/DESIGN.md) for the design and the rationale behind it.

## Install

```sh
uv sync
```

## Use

```sh
5et sync                    # fetch and index spell data (required once)
5et spell fireball          # pretty terminal output
5et spell fireball > f.md   # markdown, because stdout is not a TTY
5et spell fireball -t obsidian -o ~/vault/Spells
5et search fire --level 3 --school evocation
```

## Data and licensing

No game data is distributed with this tool. `5et sync` fetches JSON from the
[5etools-src](https://github.com/5etools-mirror-3/5etools-src) repository at a pinned release
tag into a local per-user cache. That data is Wizards of the Coast content and is not
redistributed here.
