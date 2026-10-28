"""The 5et command line interface.

Kept thin on purpose: argument parsing and output routing only, with the work
delegated to the modules under test. Two behaviors are deliberate and
documented in docs/DESIGN.md section 8:

- Rich output only when stdout is a TTY, so `5et spell fireball > f.md` yields
  clean markdown with no flag.
- A sync is never implicit. A lookup with no cache says so and exits 1 rather
  than downloading several megabytes as a side effect.
"""

from __future__ import annotations

import re
import shutil
import sys
from pathlib import Path

import click
from rich.console import Console

from fivet import __version__, config, sync
from fivet.models import Spell
from fivet.render import terminal
from fivet.render.markdown import DEFAULT_TEMPLATE, TemplateMissingError, render_spell
from fivet.render.tags import LinkStyle
from fivet.store import MatchKind, Store, StoreMissingError

# Characters a filename cannot safely carry across platforms.
_UNSAFE_FILENAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')

SYNC_HINT = "No spell data cached. Run `5et sync` first."


def _out() -> Console:
    return Console()


def _err() -> Console:
    return Console(stderr=True)


def _note(message: str) -> None:
    """Advisory output goes to stderr so it never pollutes piped markdown."""
    _err().print(f"[dim]{message}[/dim]", soft_wrap=True)


def _note_path(label: str, path: Path) -> None:
    """Paths go out unwrapped, so they stay copy-pasteable."""
    click.echo(f"{label} {path}", err=True)


def _open_store(ctx: click.Context) -> Store:
    store = sync.open_store(config.cache_dir())
    try:
        store.count()
    except StoreMissingError:
        raise click.ClickException(SYNC_HINT) from None
    ctx.call_on_close(store.close)
    return store


def _data_version(store: Store) -> str:
    return store.meta().get("version", "")


def _safe_filename(name: str) -> str:
    return _UNSAFE_FILENAME.sub("_", name).strip() or "spell"


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.version_option(__version__, prog_name="5et")
def main() -> None:
    """Look up D&D 5e spells from 5etools data and export them as markdown."""


@main.command("sync")
@click.option("--version", "version", default=None, help="Pin a release tag, e.g. v2.39.0.")
@click.option("--force", is_flag=True, help="Re-fetch even if the cache is already current.")
def sync_command(version: str | None, force: bool) -> None:
    """Fetch spell data from a pinned upstream release and rebuild the index."""
    cache = config.cache_dir()
    existing = sync.read_manifest(cache)

    if existing and not force and version and existing.get("version") == version:
        _out().print(f"Already at {version}. Use --force to re-fetch.")
        return

    console = _err()
    try:
        with console.status("[dim]Resolving version...[/dim]") as status:

            def progress(filename: str) -> None:
                status.update(f"[dim]Fetching {filename}[/dim]")

            result = sync.sync(cache, version=version, progress=progress)
    except sync.SyncError as exc:
        raise click.ClickException(str(exc)) from exc

    _out().print(
        f"Synced [bold]{result.spell_count}[/bold] spells "
        f"from [bold]{result.source_count}[/bold] sources "
        f"at [bold]{result.version}[/bold]."
    )
    _note_path("Cache:", cache)


@main.command("spell")
@click.argument("name")
@click.option("--source", "-s", default=None, help="Require a specific source, e.g. XPHB.")
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["auto", "rich", "md"]),
    default="auto",
    help="Output format. Defaults to rich on a TTY and markdown otherwise.",
)
@click.option("--template", "-t", default=None, help="Markdown template name.")
@click.option(
    "--links",
    type=click.Choice([style.value for style in LinkStyle]),
    default=None,
    help="How cross-references render in markdown.",
)
@click.option(
    "--output",
    "-o",
    "output_dir",
    type=click.Path(file_okay=False, path_type=Path),
    default=None,
    help="Write <Name>.md into this directory instead of stdout.",
)
@click.option("--force", is_flag=True, help="Overwrite an existing output file.")
@click.pass_context
def spell_command(
    ctx: click.Context,
    name: str,
    source: str | None,
    output_format: str,
    template: str | None,
    links: str | None,
    output_dir: Path | None,
    force: bool,
) -> None:
    """Look up a spell by NAME."""
    settings = config.load_settings()
    store = _open_store(ctx)

    match = store.resolve(name, settings, source=source)
    if match is None:
        message = f"No spell matching {name!r}"
        if source:
            message += f" in source {source!r}"
        suggestions = store.fuzzy_names(name, cutoff=max(50, settings.fuzzy_cutoff - 20), limit=3)
        if suggestions:
            message += ". Did you mean: " + ", ".join(n for n, _ in suggestions)
        raise click.ClickException(message + ".")

    if match.kind is not MatchKind.EXACT:
        _note(f"Matched {match.spell.name!r} ({match.kind.value}).")
    if match.is_ambiguous:
        others = ", ".join(s.source for s in match.alternatives)
        _note(f"Using {match.spell.source}; also in {others}. Use --source to choose.")

    spell = match.spell
    version = _data_version(store)

    # A file or a pipe both mean markdown; only an interactive terminal gets rich.
    wants_rich = output_format == "rich" or (
        output_format == "auto" and output_dir is None and sys.stdout.isatty()
    )

    if wants_rich:
        _out().print(terminal.spell_renderable(spell, data_version=version))
        return

    text = _render_markdown(spell, settings, template, links, version)

    if output_dir is None:
        click.echo(text, nl=False)
        return

    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{_safe_filename(spell.name)}.md"
    if path.exists() and not force:
        raise click.ClickException(f"{path} already exists. Use --force to overwrite.")
    path.write_text(text)
    click.echo(f"Wrote {path}")


def _render_markdown(
    spell: Spell,
    settings: config.Settings,
    template: str | None,
    links: str | None,
    version: str,
) -> str:
    try:
        return render_spell(
            spell,
            template=template or settings.template or DEFAULT_TEMPLATE,
            links=LinkStyle(links) if links else settings.links,
            data_version=version,
        )
    except TemplateMissingError as exc:
        raise click.ClickException(str(exc)) from exc


@main.command("search")
@click.argument("query", required=False)
@click.option("--level", "-l", type=int, default=None, help="Spell level, 0 for cantrips.")
@click.option("--school", default=None, help="School name or single-letter code.")
@click.option("--class", "class_name", default=None, help="Class that can cast it.")
@click.option("--source", "-s", default=None, help="Source abbreviation.")
@click.option("--limit", type=int, default=50, show_default=True, help="Maximum results.")
@click.pass_context
def search_command(
    ctx: click.Context,
    query: str | None,
    level: int | None,
    school: str | None,
    class_name: str | None,
    source: str | None,
    limit: int,
) -> None:
    """Search spells by name fragment and filters."""
    store = _open_store(ctx)
    results = store.search(
        query=query,
        level=level,
        school=school,
        class_name=class_name,
        source=source,
        limit=limit,
    )
    if not results:
        _note("No matching spells.")
        return

    if sys.stdout.isatty():
        _out().print(terminal.search_table(results))
    else:
        for spell in results:
            level_text = "C" if spell.level == 0 else str(spell.level)
            click.echo(f"{spell.name}\t{level_text}\t{spell.school_full}\t{spell.source}")


@main.command("sources")
@click.pass_context
def sources_command(ctx: click.Context) -> None:
    """List the source books in the cache and their spell counts."""
    store = _open_store(ctx)
    counts = store.sources()
    if sys.stdout.isatty():
        _out().print(terminal.source_table(counts))
    else:
        for source, count in counts:
            click.echo(f"{source}\t{count}")


@main.group("cache")
def cache_group() -> None:
    """Inspect or clear the local data cache."""


@cache_group.command("info")
def cache_info() -> None:
    """Show what is cached and which upstream version it came from."""
    cache = config.cache_dir()
    manifest = sync.read_manifest(cache)

    # Plain echo rather than rich, so a long cache path is never line-wrapped.
    click.echo(f"Cache:   {cache}")
    if manifest is None:
        click.echo("Status:  empty")
        _note(SYNC_HINT)
        return

    click.echo(f"Version: {manifest.get('version', 'unknown')}")
    click.echo(f"Fetched: {manifest.get('fetched_at', 'unknown')}")
    click.echo(f"Files:   {len(manifest.get('files', {}))}")

    size = sum(path.stat().st_size for path in cache.rglob("*") if path.is_file())
    click.echo(f"Size:    {size / 1e6:.1f} MB")

    store = sync.open_store(cache)
    try:
        click.echo(f"Spells:  {store.count()}")
    except StoreMissingError:
        click.echo("Spells:  no index; run `5et sync`")
    finally:
        store.close()


@cache_group.command("clear")
@click.option("--yes", is_flag=True, help="Skip the confirmation prompt.")
def cache_clear(yes: bool) -> None:
    """Delete the cached data and index."""
    cache = config.cache_dir()
    if not cache.exists():
        _out().print("Cache is already empty.")
        return
    if not yes:
        click.confirm(f"Delete {cache}?", abort=True)
    shutil.rmtree(cache)
    click.echo(f"Removed {cache}")


if __name__ == "__main__":
    main()
