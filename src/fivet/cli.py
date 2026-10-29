"""The 5et command line interface.

Kept thin on purpose: argument parsing and output routing only, with the work
delegated to the modules under test. Three behaviors are deliberate and
documented in docs/DESIGN.md section 8:

- Rich output only when stdout is a TTY, so `5et spell fireball > f.md` yields
  clean markdown with no flag.
- A sync is never implicit. A lookup with no cache says so and exits 1 rather
  than downloading several megabytes as a side effect.
- `--format json` emits the normalized display view, never the raw upstream
  record. The shapes live in `render/payloads.py`.
"""

from __future__ import annotations

import json
import re
import shutil
import sys
from collections.abc import Callable
from enum import StrEnum
from pathlib import Path
from typing import Any

import click
from rich.console import Console

from fivet import __version__, config, sync
from fivet.config import Edition
from fivet.models import Spell
from fivet.render import payloads, terminal
from fivet.render.markdown import DEFAULT_TEMPLATE, TemplateMissingError, render_spell
from fivet.render.tags import LinkStyle
from fivet.store import MatchKind, Store, StoreMissingError

# Characters a filename cannot safely carry across platforms.
_UNSAFE_FILENAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')

SYNC_HINT = "No spell data cached. Run `5et sync` first."


class OutputFormat(StrEnum):
    """What a command prints.

    `auto` resolves to `rich` on a TTY and to the command's plain format
    otherwise: markdown for one spell, tab-separated lines for a listing.
    """

    AUTO = "auto"
    RICH = "rich"
    TEXT = "text"
    MD = "md"
    JSON = "json"


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


def _emit_json(payload: dict[str, Any]) -> None:
    """One indented object per invocation, newline-terminated, on stdout."""
    click.echo(json.dumps(payload, indent=2))


def _open_store(ctx: click.Context) -> Store:
    store = sync.open_store(config.cache_dir())
    try:
        store.count()
    except StoreMissingError:
        raise click.ClickException(SYNC_HINT) from None
    ctx.call_on_close(store.close)
    return store


def _format_option(
    plain: OutputFormat = OutputFormat.TEXT,
    rich: bool = True,
) -> Callable[..., Any]:
    """Add the shared `--format` flag.

    `plain` is what `auto` falls back to off a TTY, and `rich` is false for the
    commands that report rather than present, where a panel or a table would
    add nothing.
    """
    choices = [OutputFormat.AUTO.value]
    if rich:
        choices.append(OutputFormat.RICH.value)
    choices += [plain.value, OutputFormat.JSON.value]
    fallback = f"rich on a TTY and {plain.value} otherwise" if rich else plain.value
    return click.option(
        "--format",
        "output_format",
        type=click.Choice(choices),
        default=OutputFormat.AUTO.value,
        help=f"Output format. Defaults to {fallback}.",
    )


def _resolve_format(
    output_format: str,
    plain: OutputFormat = OutputFormat.TEXT,
    rich_ok: bool = True,
) -> OutputFormat:
    requested = OutputFormat(output_format)
    if requested is not OutputFormat.AUTO:
        return requested
    if rich_ok and sys.stdout.isatty():
        return OutputFormat.RICH
    return plain


def _edition_options(command: Callable[..., Any]) -> Callable[..., Any]:
    """Add the `--2014` / `--2024` pair, shared by the commands that filter."""
    for flag, name, kept in (
        ("--2024", "revised", Edition.REVISED),
        ("--2014", "legacy", Edition.LEGACY),
    ):
        command = click.option(
            flag,
            name,
            is_flag=True,
            help=f"Only {kept.value} rules: {kept.phb} and the supplements, "
            f"never {kept.excluded_source}.",
        )(command)
    return command


def _edition(legacy: bool, revised: bool) -> Edition | None:
    if legacy and revised:
        raise click.UsageError("--2014 and --2024 are mutually exclusive.")
    if legacy:
        return Edition.LEGACY
    if revised:
        return Edition.REVISED
    return None


def _check_source_against_edition(source: str | None, edition: Edition | None) -> None:
    """Reject a `--source` the edition rules out, rather than finding nothing.

    Without this, `--2014 --source XPHB` would report no matching spell, which
    is true but hides the contradiction that caused it.
    """
    if source and edition and source.upper() == edition.excluded_source:
        raise click.UsageError(
            f"--source {source} is not available under --{edition.value}; "
            f"{edition.excluded_source} belongs to the other edition."
        )


def _data_version(store: Store) -> str:
    return store.meta().get("version", "")


def _safe_filename(name: str) -> str:
    return _UNSAFE_FILENAME.sub("_", name).strip() or "spell"


def _cache_size(cache: Path) -> int:
    return sum(path.stat().st_size for path in cache.rglob("*") if path.is_file())


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.version_option(__version__, prog_name="5et")
def main() -> None:
    """Look up D&D 5e spells from 5etools data and export them as markdown."""


@main.command("sync")
@click.option("--version", "version", default=None, help="Pin a release tag, e.g. v2.39.0.")
@click.option("--force", is_flag=True, help="Re-fetch even if the cache is already current.")
@_format_option(rich=False)
def sync_command(version: str | None, force: bool, output_format: str) -> None:
    """Fetch spell data from a pinned upstream release and rebuild the index."""
    cache = config.cache_dir()
    existing = sync.read_manifest(cache)
    fmt = _resolve_format(output_format, rich_ok=False)

    if existing and not force and version and existing.get("version") == version:
        if fmt is OutputFormat.JSON:
            _emit_json(
                {
                    "cache": str(cache),
                    "version": existing.get("version"),
                    "synced": False,
                    "spells": None,
                    "sources": None,
                }
            )
            return
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

    if fmt is OutputFormat.JSON:
        _emit_json(
            {
                "cache": str(cache),
                "version": result.version,
                "synced": True,
                "spells": result.spell_count,
                "sources": result.source_count,
            }
        )
        return

    _out().print(
        f"Synced [bold]{result.spell_count}[/bold] spells "
        f"from [bold]{result.source_count}[/bold] sources "
        f"at [bold]{result.version}[/bold]."
    )
    _note_path("Cache:", cache)


@main.command("spell")
@click.argument("name")
@click.option("--source", "-s", default=None, help="Require a specific source, e.g. XPHB.")
@_format_option(OutputFormat.MD)
@click.option("--template", "-t", default=None, help="Markdown template name.")
@click.option(
    "--links",
    type=click.Choice([style.value for style in LinkStyle]),
    default=None,
    help="How cross-references render in markdown and in JSON prose.",
)
@click.option(
    "--output",
    "-o",
    "output_dir",
    type=click.Path(file_okay=False, path_type=Path),
    default=None,
    help="Write <Name>.md or <Name>.json into this directory instead of stdout.",
)
@click.option("--force", is_flag=True, help="Overwrite an existing output file.")
@_edition_options
@click.pass_context
def spell_command(
    ctx: click.Context,
    name: str,
    source: str | None,
    legacy: bool,
    revised: bool,
    output_format: str,
    template: str | None,
    links: str | None,
    output_dir: Path | None,
    force: bool,
) -> None:
    """Look up a spell by NAME."""
    edition = _edition(legacy, revised)
    _check_source_against_edition(source, edition)
    # A file is never a terminal, so --output rules rich out before the lookup.
    fmt = _resolve_format(output_format, OutputFormat.MD, rich_ok=output_dir is None)
    if fmt is OutputFormat.RICH and output_dir is not None:
        raise click.UsageError("--format rich cannot be written to a file; drop --output.")

    settings = config.load_settings()
    store = _open_store(ctx)

    match = store.resolve(name, settings, source=source, edition=edition)
    if match is None:
        message = f"No spell matching {name!r}"
        if source:
            message += f" in source {source!r}"
        if edition:
            message += f" under the {edition.value} rules"
        suggestions = store.fuzzy_names(
            name,
            cutoff=max(50, settings.fuzzy_cutoff - 20),
            limit=3,
            edition=edition,
        )
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

    if fmt is OutputFormat.RICH:
        _out().print(terminal.spell_renderable(spell, data_version=version))
        return

    link_style = LinkStyle(links) if links else settings.links

    if fmt is OutputFormat.JSON:
        payload = payloads.spell_payload(spell, links=link_style, data_version=version)
        text = json.dumps(payload, indent=2) + "\n"
        suffix = ".json"
    else:
        text = _render_markdown(spell, settings, template, link_style, version)
        suffix = ".md"

    if output_dir is None:
        click.echo(text, nl=False)
        return

    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{_safe_filename(spell.name)}{suffix}"
    if path.exists() and not force:
        raise click.ClickException(f"{path} already exists. Use --force to overwrite.")
    path.write_text(text)
    click.echo(f"Wrote {path}")


def _render_markdown(
    spell: Spell,
    settings: config.Settings,
    template: str | None,
    links: LinkStyle,
    version: str,
) -> str:
    try:
        return render_spell(
            spell,
            template=template or settings.template or DEFAULT_TEMPLATE,
            links=links,
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
@_format_option()
@_edition_options
@click.pass_context
def search_command(
    ctx: click.Context,
    query: str | None,
    level: int | None,
    school: str | None,
    class_name: str | None,
    source: str | None,
    legacy: bool,
    revised: bool,
    limit: int,
    output_format: str,
) -> None:
    """Search spells by name fragment and filters."""
    edition = _edition(legacy, revised)
    _check_source_against_edition(source, edition)
    fmt = _resolve_format(output_format)
    store = _open_store(ctx)
    results = store.search(
        query=query,
        level=level,
        school=school,
        class_name=class_name,
        source=source,
        edition=edition,
        limit=limit,
    )

    # An empty result set is a valid answer, so JSON reports it rather than
    # leaving a consumer with nothing to parse.
    if fmt is OutputFormat.JSON:
        _emit_json(payloads.search_payload(results, data_version=_data_version(store)))
        return

    if not results:
        _note("No matching spells.")
        return

    if fmt is OutputFormat.RICH:
        _out().print(terminal.search_table(results))
        return

    for spell in results:
        level_text = "C" if spell.level == 0 else str(spell.level)
        click.echo(f"{spell.name}\t{level_text}\t{spell.school_full}\t{spell.source}")


@main.command("sources")
@_format_option()
@click.pass_context
def sources_command(ctx: click.Context, output_format: str) -> None:
    """List the source books in the cache and their spell counts."""
    fmt = _resolve_format(output_format)
    store = _open_store(ctx)
    counts = store.sources()

    if fmt is OutputFormat.JSON:
        _emit_json(payloads.sources_payload(counts, data_version=_data_version(store)))
        return

    if fmt is OutputFormat.RICH:
        _out().print(terminal.source_table(counts))
        return

    for source, count in counts:
        click.echo(f"{source}\t{count}")


@main.group("cache")
def cache_group() -> None:
    """Inspect or clear the local data cache."""


@cache_group.command("info")
@_format_option(rich=False)
def cache_info(output_format: str) -> None:
    """Show what is cached and which upstream version it came from."""
    cache = config.cache_dir()
    manifest = sync.read_manifest(cache)
    fmt = _resolve_format(output_format, rich_ok=False)

    if fmt is OutputFormat.JSON:
        _emit_json(_cache_payload(cache, manifest))
        return

    # Plain echo rather than rich, so a long cache path is never line-wrapped.
    click.echo(f"Cache:   {cache}")
    if manifest is None:
        click.echo("Status:  empty")
        _note(SYNC_HINT)
        return

    click.echo(f"Version: {manifest.get('version', 'unknown')}")
    click.echo(f"Fetched: {manifest.get('fetched_at', 'unknown')}")
    click.echo(f"Files:   {len(manifest.get('files', {}))}")
    click.echo(f"Size:    {_cache_size(cache) / 1e6:.1f} MB")

    store = sync.open_store(cache)
    try:
        click.echo(f"Spells:  {store.count()}")
    except StoreMissingError:
        click.echo("Spells:  no index; run `5et sync`")
    finally:
        store.close()


def _cache_payload(cache: Path, manifest: dict[str, Any] | None) -> dict[str, Any]:
    """Every key is always present; `null` means not cached rather than absent."""
    payload: dict[str, Any] = {
        "cache": str(cache),
        "cached": manifest is not None,
        "version": None,
        "fetched_at": None,
        "files": None,
        "size_bytes": None,
        "spells": None,
    }
    if manifest is None:
        return payload

    payload["version"] = manifest.get("version")
    payload["fetched_at"] = manifest.get("fetched_at")
    payload["files"] = len(manifest.get("files", {}))
    payload["size_bytes"] = _cache_size(cache)

    store = sync.open_store(cache)
    try:
        payload["spells"] = store.count()
    except StoreMissingError:
        payload["spells"] = None
    finally:
        store.close()
    return payload


@cache_group.command("clear")
@click.option("--yes", is_flag=True, help="Skip the confirmation prompt.")
@_format_option(rich=False)
def cache_clear(yes: bool, output_format: str) -> None:
    """Delete the cached data and index."""
    cache = config.cache_dir()
    fmt = _resolve_format(output_format, rich_ok=False)
    json_out = fmt is OutputFormat.JSON

    if not cache.exists():
        if json_out:
            _emit_json({"cache": str(cache), "removed": False})
            return
        _out().print("Cache is already empty.")
        return

    if not yes:
        # The prompt goes to stderr so it cannot land in the middle of JSON.
        click.confirm(f"Delete {cache}?", abort=True, err=True)

    shutil.rmtree(cache)
    if json_out:
        _emit_json({"cache": str(cache), "removed": True})
        return
    click.echo(f"Removed {cache}")


if __name__ == "__main__":
    main()
