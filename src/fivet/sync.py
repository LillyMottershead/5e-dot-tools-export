"""Fetching 5etools spell data into the local cache.

Per docs/DESIGN.md section 4.2, data is pulled as individual raw files at a
pinned release tag rather than from the release zip, because the zip is 49.6 MB
of which roughly 48 MB is JavaScript, CSS and fonts we would never read.

A sync is never implicit. Downloading several megabytes as a side effect of a
lookup is a surprise, and surprises in a tool reached for reflexively are worse
than one extra command on first run.

No game data is distributed with this tool; it is fetched here at runtime into
a per-user cache. See the licensing note in docs/DESIGN.md section 2.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from fivet import __version__
from fivet.store import Store, load_spells

REPO = "5etools-mirror-3/5etools-src"
API_BASE = "https://api.github.com"
RAW_BASE = "https://raw.githubusercontent.com"
DATA_PATH = "data/spells"

INDEX_FILE = "index.json"
SOURCES_FILE = "sources.json"
MANIFEST_FILE = "manifest.json"
INDEX_DB = "index.db"
RAW_DIR = "raw"

USER_AGENT = f"5et/{__version__} (+https://github.com/{REPO})"
TIMEOUT = httpx.Timeout(30.0, connect=10.0)


class SyncError(RuntimeError):
    """A sync could not complete. The message is intended for the user."""


@dataclass
class SyncResult:
    version: str
    spell_count: int
    source_count: int
    files: dict[str, str] = field(default_factory=dict)
    fetched_at: str = ""


def _client(client: httpx.Client | None = None) -> tuple[httpx.Client, bool]:
    """Return a client and whether we own it, so callers can inject one."""
    if client is not None:
        return client, False
    return httpx.Client(timeout=TIMEOUT, headers={"User-Agent": USER_AGENT}), True


def resolve_latest_version(client: httpx.Client | None = None) -> str:
    """Read the newest release tag from the GitHub API."""
    http, owned = _client(client)
    try:
        response = http.get(f"{API_BASE}/repos/{REPO}/releases/latest")
        if response.status_code != 200:
            raise SyncError(
                f"Could not read the latest release tag (HTTP {response.status_code}). "
                "Pass --version to pin one explicitly."
            )
        tag = response.json().get("tag_name")
        if not tag:
            raise SyncError("The latest release carries no tag name.")
        return tag
    except httpx.HTTPError as exc:
        raise SyncError(f"Could not reach the GitHub API: {exc}") from exc
    finally:
        if owned:
            http.close()


def _fetch(http: httpx.Client, version: str, filename: str) -> bytes:
    url = f"{RAW_BASE}/{REPO}/{version}/{DATA_PATH}/{filename}"
    try:
        response = http.get(url)
    except httpx.HTTPError as exc:
        raise SyncError(f"Could not fetch {filename}: {exc}") from exc
    if response.status_code == 404:
        raise SyncError(
            f"{filename} does not exist at version {version}. "
            "Check the version tag with `5et sync --version <tag>`."
        )
    if response.status_code != 200:
        raise SyncError(f"Could not fetch {filename} (HTTP {response.status_code}).")
    return response.content


def fetch_data(
    version: str,
    client: httpx.Client | None = None,
    progress: Callable[[str], None] | None = None,
) -> dict[str, bytes]:
    """Fetch the spell index, every source file it lists, and sources.json."""
    http, owned = _client(client)
    try:
        if progress:
            progress(INDEX_FILE)
        files: dict[str, bytes] = {INDEX_FILE: _fetch(http, version, INDEX_FILE)}

        try:
            index = json.loads(files[INDEX_FILE])
        except json.JSONDecodeError as exc:
            raise SyncError(f"{INDEX_FILE} at {version} is not valid JSON: {exc}") from exc

        for filename in sorted(set(index.values())):
            if progress:
                progress(filename)
            files[filename] = _fetch(http, version, filename)

        if progress:
            progress(SOURCES_FILE)
        files[SOURCES_FILE] = _fetch(http, version, SOURCES_FILE)
        return files
    finally:
        if owned:
            http.close()


def write_cache(cache_dir: Path, files: dict[str, bytes], version: str) -> dict[str, Any]:
    """Write fetched files and a manifest recording the version and hashes."""
    raw_dir = cache_dir / RAW_DIR
    raw_dir.mkdir(parents=True, exist_ok=True)

    hashes = {}
    for filename, content in files.items():
        (raw_dir / filename).write_bytes(content)
        hashes[filename] = hashlib.sha256(content).hexdigest()

    manifest = {
        "version": version,
        "fetched_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "tool_version": __version__,
        "files": hashes,
    }
    (cache_dir / MANIFEST_FILE).write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def read_manifest(cache_dir: Path) -> dict[str, Any] | None:
    path = cache_dir / MANIFEST_FILE
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        return None


def build_class_index(sources: dict[str, Any]) -> dict[tuple[str, str], list[str]]:
    """Invert data/spells/sources.json into (source, name) to class names.

    The join key is the pair, not the name alone, because the 2014 and 2024
    versions of a spell can list different classes. Only `class` is read;
    `classVariant` describes optional-feature grants and needs its own
    presentation to mean anything.
    """
    index: dict[tuple[str, str], list[str]] = {}
    for source, spells in sources.items():
        if not isinstance(spells, dict):
            continue
        for name, entry in spells.items():
            if not isinstance(entry, dict):
                continue
            names = sorted({c["name"] for c in entry.get("class", []) if c.get("name")})
            if names:
                index[(source.upper(), name.lower())] = names
    return index


def load_cached_spells(cache_dir: Path) -> list:
    """Read the cached raw files and build Spell models with class data."""
    raw_dir = cache_dir / RAW_DIR
    index_path = raw_dir / INDEX_FILE
    if not index_path.is_file():
        raise SyncError(f"No cached data in {cache_dir}. Run `5et sync` first.")

    index = json.loads(index_path.read_text())
    raw_by_source: dict[str, list[dict[str, Any]]] = {}
    for source, filename in index.items():
        path = raw_dir / filename
        if not path.is_file():
            continue
        payload = json.loads(path.read_text())
        raw_by_source[source] = payload.get("spell", [])

    sources_path = raw_dir / SOURCES_FILE
    classes: dict[tuple[str, str], list[str]] = {}
    if sources_path.is_file():
        classes = build_class_index(json.loads(sources_path.read_text()))

    return load_spells(raw_by_source, classes)


def sync(
    cache_dir: Path,
    version: str | None = None,
    client: httpx.Client | None = None,
    progress: Callable[[str], None] | None = None,
) -> SyncResult:
    """Fetch data at a pinned version, cache it, and rebuild the index.

    Without an explicit version this pins whatever is newest at this moment and
    never drifts afterward, so a cache is always a snapshot of a known upstream
    release.
    """
    resolved = version or resolve_latest_version(client)
    files = fetch_data(resolved, client=client, progress=progress)
    manifest = write_cache(cache_dir, files, resolved)

    spells = load_cached_spells(cache_dir)
    if not spells:
        raise SyncError(f"No spells found in the data at version {resolved}.")

    Store.build(
        cache_dir / INDEX_DB,
        spells,
        meta={"version": resolved, "fetched_at": manifest["fetched_at"]},
    )

    return SyncResult(
        version=resolved,
        spell_count=len(spells),
        source_count=len({s.source for s in spells}),
        files=manifest["files"],
        fetched_at=manifest["fetched_at"],
    )


def open_store(cache_dir: Path) -> Store:
    """Open the index, or fail with a message naming the sync command."""
    return Store(cache_dir / INDEX_DB)
