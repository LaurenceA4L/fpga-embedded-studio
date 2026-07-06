# fpga-embedded-studio — GUI tracked-input cache/sync-status tests
#
# Copyright (C) 2026 Laurence <laurence@anodes4life.com>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

"""
Exercises the data/ working-copy cache: Load actions copy their source into
data/ and register a TrackedInput; /inputs/status flags drift without
touching the cache; /inputs/refresh is the only thing that re-copies.
"""

import os
import shutil
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from web.gui.app import CACHE_ROOT, app, state

REPO_ROOT = Path(__file__).parent.parent.parent
SOPCINFO = REPO_ROOT / "submodules/sopc2dts/tests/fixtures/a7_system.sopcinfo"
BOARDINFO = REPO_ROOT / "submodules/sopc2dts/tests/fixtures/boardinfo_a7.xml"
HPS_DTS = REPO_ROOT / "submodules/dts-merge/tests/fixtures/hps/socfpga_agilex7_socdk.dts"
HPS_INCLUDE = REPO_ROOT / "submodules/dts-merge/tests/fixtures/hps/include"


@pytest.fixture(autouse=True)
def _reset_state():
    state.system = None
    state.boardinfo = None
    state.boardinfo_path = ""
    state.hps_path = ""
    state.hps_include_dirs = ""
    state.hps_parsed = None
    state.merge_result = None
    state.tracked_inputs = {}
    state.tracked_includes = []
    shutil.rmtree(CACHE_ROOT, ignore_errors=True)
    yield
    shutil.rmtree(CACHE_ROOT, ignore_errors=True)


@pytest.fixture
def client():
    return TestClient(app)


def _load_system(client):
    return client.post("/load", data={"input_path": str(SOPCINFO)})


def test_load_copies_sopcinfo_into_cache(client):
    _load_system(client)
    entry = state.tracked_inputs["sopcinfo"]
    assert entry.cache_path.exists()
    assert entry.cache_path.read_bytes() == SOPCINFO.read_bytes()
    assert entry.status == "in_sync"
    # The system is parsed from the cached copy, not the original path.
    assert str(CACHE_ROOT) in str(entry.cache_path)


def test_load_hps_copies_dts_and_include_dirs(client):
    _load_system(client)
    r = client.post(
        "/merge/load-hps",
        data={"hps_path": str(HPS_DTS), "include_dirs": str(HPS_INCLUDE)},
    )
    assert "Error" not in r.text

    hps_entry = state.tracked_inputs["hps"]
    assert hps_entry.cache_path.exists()
    # Sibling .dtsi files (same-dir #include chain) got copied alongside it.
    assert (hps_entry.cache_path.parent / "socfpga_agilex.dtsi").exists()

    assert len(state.tracked_includes) == 1
    include_entry = state.tracked_includes[0]
    assert (include_entry.cache_path / "dt-bindings" / "gpio" / "gpio.h").exists()


def test_status_flags_changed_source_without_touching_cache(client):
    _load_system(client)
    entry = state.tracked_inputs["sopcinfo"]
    cached_bytes_before = entry.cache_path.read_bytes()

    # Mutate the *original* fixture in place, then restore it in a finally
    # block so we don't leave the repo's tracked fixture dirty.
    original_bytes = SOPCINFO.read_bytes()
    try:
        with open(SOPCINFO, "ab") as f:
            f.write(b"\n")
        os.utime(SOPCINFO, None)  # ensure mtime actually advances

        r = client.get("/inputs/status")
        assert "changed" in r.text.lower()
        assert state.tracked_inputs["sopcinfo"].status == "changed"
        # Cache must be untouched by a mere status check.
        assert entry.cache_path.read_bytes() == cached_bytes_before
    finally:
        SOPCINFO.write_bytes(original_bytes)


def test_refresh_recopies_and_returns_to_in_sync(client):
    _load_system(client)
    entry = state.tracked_inputs["sopcinfo"]

    original_bytes = SOPCINFO.read_bytes()
    try:
        with open(SOPCINFO, "ab") as f:
            f.write(b"\n")
        os.utime(SOPCINFO, None)
        client.get("/inputs/status")
        assert state.tracked_inputs["sopcinfo"].status == "changed"

        r = client.post("/inputs/refresh", data={"slot": entry.slot})
        assert "Error" not in r.text
        assert state.tracked_inputs["sopcinfo"].status == "in_sync"
        assert state.tracked_inputs["sopcinfo"].cache_path.read_bytes() == SOPCINFO.read_bytes()
    finally:
        SOPCINFO.write_bytes(original_bytes)


def test_status_reports_missing_source(client, tmp_path):
    doomed = tmp_path / "will_be_deleted.sopcinfo"
    doomed.write_bytes(SOPCINFO.read_bytes())
    client.post("/load", data={"input_path": str(doomed)})
    assert state.tracked_inputs["sopcinfo"].status == "in_sync"

    doomed.unlink()
    r = client.get("/inputs/status")
    assert "missing" in r.text.lower()
    assert state.tracked_inputs["sopcinfo"].status == "missing"
