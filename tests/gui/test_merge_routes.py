# fpga-embedded-studio — GUI merge route tests
#
# Copyright (C) 2026 Laurence <laurence@anodes4life.com>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

"""
Exercises the /merge* routes added to the sopc2dts GUI, wiring together the
two real submodules exactly as a user would: load the bundled A7 sopcinfo
fixture (sopc2dts), load the bundled real Agilex 7 HPS devicetree chain
(dts-merge), compute the merge, resolve every conflict, and download the
result.
"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from web.gui.app import app, state

REPO_ROOT = Path(__file__).parent.parent.parent
SOPCINFO = REPO_ROOT / "submodules/sopc2dts/tests/fixtures/a7_system.sopcinfo"
BOARDINFO = REPO_ROOT / "submodules/sopc2dts/tests/fixtures/boardinfo_a7.xml"
HPS_DTS = REPO_ROOT / "submodules/dts-merge/tests/fixtures/hps/socfpga_agilex7_socdk.dts"
HPS_INCLUDE = REPO_ROOT / "submodules/dts-merge/tests/fixtures/hps/include"


@pytest.fixture(autouse=True)
def _reset_state():
    """The GUI's ``state`` is a module-level singleton — reset it per test."""
    import shutil
    from web.gui.app import CACHE_ROOT

    state.system = None
    state.boardinfo = None
    state.boardinfo_path = ""
    state.hps_path = ""
    state.hps_include_dirs = ""
    state.hps_parsed = None
    state.merge_anchor = ""
    state.fpga_anchor = "sopc0"
    state.merge_result = None
    state.tracked_inputs = {}
    state.tracked_includes = []
    shutil.rmtree(CACHE_ROOT, ignore_errors=True)
    yield
    shutil.rmtree(CACHE_ROOT, ignore_errors=True)


@pytest.fixture
def client():
    return TestClient(app)


def test_index_renders_merge_section(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "Merge into HPS/kernel DTS" in r.text
    assert "Load a sopcinfo/.qsys system above first." in r.text


def test_merge_requires_system_loaded(client):
    r = client.post("/merge", data={"anchor_label": "soc0", "fpga_anchor_label": "sopc0"})
    assert "Load a sopcinfo/.qsys system first." in r.text


def _load_system(client):
    r = client.post("/load", data={"input_path": str(SOPCINFO)})
    assert "err" not in r.text.lower() or "System:" in r.text
    # Matches the real pipeline (and the dts-merge integration test's fixture
    # pairing): without the boardinfo's POV, sopc2dts falls back to a
    # different POV component and the merge conflict count no longer matches.
    client.post("/load-board", data={"board_path": str(BOARDINFO)})
    return r


def test_merge_requires_hps_loaded(client):
    _load_system(client)
    r = client.post("/merge", data={"anchor_label": "soc0", "fpga_anchor_label": "sopc0"})
    assert "Load an HPS/kernel DTS file first." in r.text


def test_loading_system_unlocks_merge_section_via_oob_swap(client):
    """
    Regression test: /load only targets #system-section, so the merge
    section (rendered once at initial page load, gated on state.system)
    would otherwise stay stuck showing "load a system first" until some
    merge-specific control was touched. /load must also ship an
    out-of-band swap for #merge-section.
    """
    r = client.post("/load", data={"input_path": str(SOPCINFO)})
    assert 'id="merge-section" hx-swap-oob="true"' in r.text
    assert "Load a sopcinfo/.qsys system above first." not in r.text


def test_load_hps_reports_missing_file(client):
    r = client.post("/merge/load-hps", data={"hps_path": "/no/such/file.dts", "include_dirs": ""})
    assert "Error" in r.text
    assert "File not found" in r.text


def test_load_hps_via_relative_default_paths(client):
    """
    Regression test: the dropdown suggests state.hps_default/hps_include_default
    as plain relative paths (e.g. "tests/fixtures/hps/socfpga_agilex7_socdk.dts"),
    resolved against the dts_merge package root — same as hps_path already was.
    include_dirs used to be resolved against the server's CWD instead, so
    picking the suggested include-dirs default broke with a cpp
    "No such file or directory" on the dt-bindings headers.
    """
    _load_system(client)
    r = client.post(
        "/merge/load-hps",
        data={"hps_path": state.hps_default, "include_dirs": state.hps_include_default},
    )
    assert "Error" not in r.text
    assert '<span class="ok">' in r.text


def test_full_merge_flow_matches_engine_expectations(client):
    _load_system(client)

    r = client.post(
        "/merge/load-hps",
        data={"hps_path": str(HPS_DTS), "include_dirs": str(HPS_INCLUDE)},
    )
    assert "Not loaded" not in r.text
    assert str(HPS_DTS) in r.text

    r = client.post("/merge", data={"anchor_label": "soc0", "fpga_anchor_label": "sopc0"})
    assert "Conflicts" in r.text
    # The known real-world result against the actual build artefact: the 5
    # shared simple-bus properties, plus the genuine collision between the
    # GHRD's generic led_pio (already baked into this HPS chain by the real
    # build) and sopc2dts's own qualified led_pio.
    assert r.text.count('class="err">unresolved</td>') == 6
    assert state.merge_result is not None
    assert len(state.merge_result.conflicts) == 6

    # Downloading before every conflict is resolved is refused.
    r = client.get("/merge/download")
    assert r.status_code == 404

    for i in range(len(state.merge_result.conflicts)):
        r = client.post("/merge/resolve", data={"index": i, "choice": "fpga"})
    assert "All conflicts resolved." in r.text
    assert state.merge_result.unresolved == []

    r = client.get("/merge/download")
    assert r.status_code == 200
    assert b"clkmgr" in r.content  # untouched real HPS peripheral
    # "fpga" was chosen for the led_pio collision too: the generic GHRD one
    # (gpio@f9001080) is gone, replaced by sopc2dts's real one (gpio@1000).
    assert b"gpio@1000" in r.content
    assert b"gpio@f9001080" not in r.content
