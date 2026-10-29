# Working in this repository

A Python CLI that looks up D&D 5e spells from [5etools](https://5e.tools) data and exports them as markdown. There is no upstream API; the data layer is the JSON that 5etools ships, fetched at a pinned release tag.

- Layout and dependency direction: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
- Design, rationale, and confirmed facts about the upstream data: [docs/DESIGN.md](docs/DESIGN.md)

Read DESIGN.md section 3 before touching anything that parses spell fields. It records the complete observed variant sets, so you can check a shape instead of guessing at one.

## Commands

```sh
uv sync
uv run pytest                      # offline, under a second
uv run ruff check . && uv run ruff format .
uv run 5et sync                    # populate the cache; needed for manual checks
uv run pytest --snapshot-update    # after an intentional renderer change
```

## Constraints

Never commit game data or spell text. It is Wizards of the Coast content, fetched at runtime into a per-user cache. Test fixtures are hand-written shapes; snapshot fixtures mirror the structure of a real spell and name it in a comment rather than copying it.

Match upstream semantics rather than inventing them. Rendering rules live in `js/parser.js` and `js/render.js` in the source repo, chiefly the `Renderer.tag` classes and their `_getStripped` methods. When you port a rule, say in a comment that it came from upstream, and say why if you deviate. Guessing here has already produced one bug worth eight times the correct damage.

Keep stdout clean. Markdown goes to stdout, advisory notes go to stderr, so `5et spell x > f.md` stays usable. Rich output only on a TTY.

Degrade, do not crash. An unknown tag renders as its first argument, an unknown entry type yields its children, and an unrecognized upstream field passes through the model. Upstream ships weekly and must not be able to break a lookup.

## Expectations for changes

Add tests with the change, not after. Every module has a matching `test_<module>.py`.

Validate against the real corpus before claiming a parsing or rendering change works. Fixtures prove the shape is handled; only 969 real spells prove the shape was right. There is a pattern for this in `tests/test_integration.py`, and ad hoc scripts belong in the scratchpad, not the repo.

Record a design decision where it belongs. A choice that outlives the session goes in DESIGN.md, and section 13 is where divergences from the original design are kept with their reasoning.
