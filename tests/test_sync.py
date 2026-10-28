"""Tests for fetching and caching.

All HTTP is mocked with respx; these tests never reach the network. The payloads
are hand-written and minimal, matching the real file shapes.
"""

import json

import httpx
import pytest
import respx

from fivet import sync
from fivet.store import Store
from fivet.sync import SyncError

VERSION = "v2.39.0"
RAW = f"{sync.RAW_BASE}/{sync.REPO}/{VERSION}/{sync.DATA_PATH}"

INDEX = {"XPHB": "spells-xphb.json", "PHB": "spells-phb.json"}

XPHB_SPELLS = {
    "spell": [
        {
            "name": "Test Blast",
            "source": "XPHB",
            "level": 3,
            "school": "V",
            "time": [{"number": 1, "unit": "action"}],
            "range": {"type": "point", "distance": {"type": "feet", "amount": 150}},
            "components": {"v": True},
            "duration": [{"type": "instant"}],
            "entries": ["It blasts."],
        }
    ]
}

PHB_SPELLS = {
    "spell": [
        {
            "name": "Test Blast",
            "source": "PHB",
            "level": 3,
            "school": "V",
            "time": [{"number": 1, "unit": "action"}],
            "range": {"type": "point", "distance": {"type": "feet", "amount": 150}},
            "components": {"v": True},
            "duration": [{"type": "instant"}],
            "entries": ["It blasts, classically."],
        }
    ]
}

SOURCES = {
    "XPHB": {"Test Blast": {"class": [{"name": "Wizard", "source": "XPHB"}]}},
    "PHB": {
        "Test Blast": {
            "class": [
                {"name": "Sorcerer", "source": "PHB"},
                {"name": "Wizard", "source": "PHB"},
            ]
        }
    },
}


def mock_all(router, version=VERSION):
    """Register the full happy-path route set."""
    base = f"{sync.RAW_BASE}/{sync.REPO}/{version}/{sync.DATA_PATH}"
    router.get(f"{sync.API_BASE}/repos/{sync.REPO}/releases/latest").respond(
        json={"tag_name": version}
    )
    router.get(f"{base}/index.json").respond(json=INDEX)
    router.get(f"{base}/spells-xphb.json").respond(json=XPHB_SPELLS)
    router.get(f"{base}/spells-phb.json").respond(json=PHB_SPELLS)
    router.get(f"{base}/sources.json").respond(json=SOURCES)


class TestResolveVersion:
    @respx.mock
    def test_reads_the_latest_tag(self):
        respx.get(f"{sync.API_BASE}/repos/{sync.REPO}/releases/latest").respond(
            json={"tag_name": VERSION}
        )
        assert sync.resolve_latest_version() == VERSION

    @respx.mock
    def test_api_failure_suggests_pinning(self):
        respx.get(f"{sync.API_BASE}/repos/{sync.REPO}/releases/latest").respond(403)
        with pytest.raises(SyncError, match="--version"):
            sync.resolve_latest_version()

    @respx.mock
    def test_a_tagless_release_is_an_error(self):
        respx.get(f"{sync.API_BASE}/repos/{sync.REPO}/releases/latest").respond(json={})
        with pytest.raises(SyncError, match="no tag name"):
            sync.resolve_latest_version()

    @respx.mock
    def test_network_failure_is_reported_not_raised_raw(self):
        respx.get(f"{sync.API_BASE}/repos/{sync.REPO}/releases/latest").mock(
            side_effect=httpx.ConnectError("down")
        )
        with pytest.raises(SyncError, match="Could not reach"):
            sync.resolve_latest_version()


class TestFetchData:
    @respx.mock
    def test_fetches_the_index_then_every_file_it_lists(self):
        mock_all(respx)
        files = sync.fetch_data(VERSION)
        assert set(files) == {
            "index.json",
            "spells-xphb.json",
            "spells-phb.json",
            "sources.json",
        }

    @respx.mock
    def test_reports_progress_per_file(self):
        mock_all(respx)
        seen = []
        sync.fetch_data(VERSION, progress=seen.append)
        assert seen[0] == "index.json"
        assert "sources.json" in seen

    @respx.mock
    def test_a_bad_version_names_the_version_flag(self):
        respx.get(f"{RAW}/index.json").respond(404)
        with pytest.raises(SyncError, match="does not exist at version"):
            sync.fetch_data(VERSION)

    @respx.mock
    def test_malformed_index_is_reported_clearly(self):
        respx.get(f"{RAW}/index.json").respond(content=b"not json")
        with pytest.raises(SyncError, match="not valid JSON"):
            sync.fetch_data(VERSION)

    @respx.mock
    def test_server_error_is_wrapped(self):
        respx.get(f"{RAW}/index.json").respond(500)
        with pytest.raises(SyncError, match="HTTP 500"):
            sync.fetch_data(VERSION)


class TestWriteCache:
    def test_writes_files_and_a_manifest(self, tmp_path):
        files = {"a.json": b'{"x": 1}'}
        manifest = sync.write_cache(tmp_path, files, VERSION)
        assert (tmp_path / "raw" / "a.json").read_bytes() == b'{"x": 1}'
        assert manifest["version"] == VERSION
        assert manifest["files"]["a.json"].isalnum()

    def test_manifest_round_trips(self, tmp_path):
        sync.write_cache(tmp_path, {"a.json": b"{}"}, VERSION)
        assert sync.read_manifest(tmp_path)["version"] == VERSION

    def test_hashes_track_content_so_a_change_is_detectable(self, tmp_path):
        import hashlib

        content = b'{"x": 1}'
        manifest = sync.write_cache(tmp_path, {"a.json": content}, VERSION)
        assert manifest["files"]["a.json"] == hashlib.sha256(content).hexdigest()

        changed = sync.write_cache(tmp_path, {"a.json": b'{"x": 2}'}, VERSION)
        assert changed["files"]["a.json"] != manifest["files"]["a.json"]

    def test_manifest_records_the_version_for_citation_in_exports(self, tmp_path):
        manifest = sync.write_cache(tmp_path, {"a.json": b"{}"}, VERSION)
        assert manifest["version"] == VERSION
        assert manifest["fetched_at"]
        assert manifest["tool_version"]

    def test_missing_manifest_reads_as_none(self, tmp_path):
        assert sync.read_manifest(tmp_path) is None

    def test_corrupt_manifest_reads_as_none_rather_than_raising(self, tmp_path):
        (tmp_path / "manifest.json").write_text("{ broken")
        assert sync.read_manifest(tmp_path) is None


class TestClassIndex:
    def test_inverts_sources_json(self):
        index = sync.build_class_index(SOURCES)
        assert index[("XPHB", "test blast")] == ["Wizard"]
        assert index[("PHB", "test blast")] == ["Sorcerer", "Wizard"]

    def test_class_variant_is_ignored(self):
        """classVariant describes optional-feature grants, not base access."""
        sources = {"TCE": {"X": {"classVariant": [{"name": "Artificer", "source": "TCE"}]}}}
        assert sync.build_class_index(sources) == {}

    def test_entries_without_classes_are_skipped(self):
        assert sync.build_class_index({"XPHB": {"X": {}}}) == {}

    def test_malformed_shapes_do_not_raise(self):
        assert sync.build_class_index({"XPHB": "unexpected"}) == {}
        assert sync.build_class_index({"XPHB": {"X": "unexpected"}}) == {}


class TestSync:
    @respx.mock
    def test_end_to_end_builds_a_usable_index(self, tmp_path):
        mock_all(respx)
        result = sync.sync(tmp_path)
        assert result.version == VERSION
        assert result.spell_count == 2
        assert result.source_count == 2

        with Store(tmp_path / "index.db") as store:
            match = store.resolve("Test Blast")
            assert match.spell.source == "XPHB"
            assert match.spell.classes == ["Wizard"]
            assert [s.source for s in match.alternatives] == ["PHB"]

    @respx.mock
    def test_an_explicit_version_skips_the_api_call(self, tmp_path):
        route = respx.get(f"{sync.API_BASE}/repos/{sync.REPO}/releases/latest").respond(
            json={"tag_name": "should-not-be-used"}
        )
        mock_all(respx)
        sync.sync(tmp_path, version=VERSION)
        assert not route.called

    @respx.mock
    def test_the_index_records_the_data_version(self, tmp_path):
        """Exported markdown cites this, so it has to be stored."""
        mock_all(respx)
        sync.sync(tmp_path, version=VERSION)
        with Store(tmp_path / "index.db") as store:
            assert store.meta()["version"] == VERSION

    @respx.mock
    def test_empty_data_is_an_error_not_an_empty_index(self, tmp_path):
        base = f"{sync.RAW_BASE}/{sync.REPO}/{VERSION}/{sync.DATA_PATH}"
        respx.get(f"{base}/index.json").respond(json={"XPHB": "spells-xphb.json"})
        respx.get(f"{base}/spells-xphb.json").respond(json={"spell": []})
        respx.get(f"{base}/sources.json").respond(json={})
        with pytest.raises(SyncError, match="No spells found"):
            sync.sync(tmp_path, version=VERSION)

    @respx.mock
    def test_resync_replaces_the_previous_index(self, tmp_path):
        mock_all(respx)
        sync.sync(tmp_path, version=VERSION)
        sync.sync(tmp_path, version=VERSION)
        with Store(tmp_path / "index.db") as store:
            assert store.count() == 2


class TestLoadCachedSpells:
    def test_requires_a_cache(self, tmp_path):
        with pytest.raises(SyncError, match="Run `5et sync`"):
            sync.load_cached_spells(tmp_path)

    def test_a_missing_source_file_is_skipped_not_fatal(self, tmp_path):
        raw = tmp_path / "raw"
        raw.mkdir()
        (raw / "index.json").write_text(json.dumps(INDEX))
        (raw / "spells-xphb.json").write_text(json.dumps(XPHB_SPELLS))
        spells = sync.load_cached_spells(tmp_path)
        assert [s.source for s in spells] == ["XPHB"]

    def test_class_data_is_optional(self, tmp_path):
        raw = tmp_path / "raw"
        raw.mkdir()
        (raw / "index.json").write_text(json.dumps({"XPHB": "spells-xphb.json"}))
        (raw / "spells-xphb.json").write_text(json.dumps(XPHB_SPELLS))
        assert sync.load_cached_spells(tmp_path)[0].classes == []
