# sopc2dts - Devicetree generation for Altera systems
#
# Python port Copyright (C) 2026 Laurence <laurence@anodes4life.com>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

"""
FastAPI application for the sopc2dts web GUI.

Single-user -- state is a module-level singleton (this is a local desktop tool,
not a multi-tenant web service).
"""

from __future__ import annotations

import asyncio
import logging
import queue
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, Response, StreamingResponse
from fastapi.templating import Jinja2Templates

# ---------------------------------------------------------------------------
# Application state
# ---------------------------------------------------------------------------

class _AppState:
    def __init__(self) -> None:
        # Defaults pre-fill the input fields but are NOT treated as loaded
        self.sopcinfo_default: str = "tests/fixtures/a7_system.sopcinfo"
        self.boardinfo_default: str = "tests/fixtures/boardinfo_a7.xml"
        # Set only when actually loaded by the user
        self.prefill_input: str = ""
        self.system = None
        self.boardinfo = None
        self.boardinfo_path: str = ""
        self.last_output: Optional[bytes | str] = None
        self.last_output_type: str = "dts"

        # --- dts-merge (HPS/kernel DTS <- sopc2dts fabric DTS) ---
        # Default points at the real build artefact bundled as a dts-merge
        # test fixture: reconstructed from the exact cp/sed steps
        # meta-intel-fpga-refdes's device-tree.bb runs for MACHINE
        # agilex7_dk_si_agf014eb (see tests/integration/test_agilex7_integration.py
        # in the dts-merge submodule for how it's assembled/why it's real).
        self.hps_default: str = "tests/fixtures/hps/socfpga_agilex7_socdk.dts"
        self.hps_include_default: str = "tests/fixtures/hps/include"
        self.hps_path: str = ""
        self.hps_include_dirs: str = ""
        self.hps_parsed = None            # dts_merge.parser.ParsedDTS
        self.merge_anchor: str = ""
        self.fpga_anchor: str = "sopc0"   # DTGenerator always labels its container "sopc0"
        self.merge_result = None          # dts_merge.merge.MergeResult


state = _AppState()

# ---------------------------------------------------------------------------
# Log capture
# ---------------------------------------------------------------------------

_log_queue: queue.Queue[str] = queue.Queue(maxsize=500)


class _GUILogHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        try:
            _log_queue.put_nowait(self.format(record))
        except queue.Full:
            pass


_gui_handler = _GUILogHandler()
_gui_handler.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
_gui_handler.setLevel(logging.WARNING)  # change to DEBUG for verbose GUI log
_root = logging.getLogger()
_root.setLevel(logging.DEBUG)
_root.addHandler(_gui_handler)

# ---------------------------------------------------------------------------
# FastAPI app + templates
# ---------------------------------------------------------------------------

app = FastAPI(title="sopc2dts GUI", docs_url=None, redoc_url=None)
_tpl_dir = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(_tpl_dir))

# Wire package version so generated headers don't say "unknown"
try:
    from importlib.metadata import version as _pkg_version, PackageNotFoundError
    from sopc2dts_py.model.system import AvalonSystem as _AS
    try:
        _AS.set_sopc2dts_version(_pkg_version("sopc2dts"))
    except PackageNotFoundError:
        _AS.set_sopc2dts_version("dev")
except Exception:
    pass

# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/health")
def health() -> dict:
    return {"ok": True}


@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "prefill_input": state.prefill_input or state.sopcinfo_default,
            "boardinfo_path": state.boardinfo_path,
            "boardinfo_default": state.boardinfo_default,
            "system_html": _render_system_html() if state.system else "",
            "merge_html": _render_merge_html(),
        },
    )


@app.post("/load", response_class=HTMLResponse)
async def load(input_path: str = Form(...)) -> HTMLResponse:
    err = _do_load(input_path.strip())
    if err:
        return HTMLResponse(f'<p class="err">Error: {err}</p>')
    return HTMLResponse(_render_system_html() + _render_merge_section_oob())


@app.post("/load-board", response_class=HTMLResponse)
async def load_board(board_path: str = Form(...)) -> HTMLResponse:
    board_path = board_path.strip()
    if not board_path:
        state.boardinfo = None
        state.boardinfo_path = ""
        state.merge_result = None  # POV/boardinfo changed; any prior merge is stale
        return HTMLResponse('<span class="ok">Using default board settings.</span>' + _render_merge_section_oob())
    p = Path(board_path)
    if not p.is_absolute() and not p.exists():
        import sopc2dts_py as _pkg
        p = Path(_pkg.__file__).parent.parent / board_path
    if not p.exists():
        return HTMLResponse(f'<span class="err">File not found: {board_path}</span>')
    try:
        from sopc2dts_py.parsers import load_boardinfo
        state.boardinfo = load_boardinfo(str(p))
        state.boardinfo_path = board_path
        state.merge_result = None  # POV/boardinfo changed; any prior merge is stale
        pov = state.boardinfo.pov or ""
        oob = (
            '<input id="pov-input" name="pov" type="text" '
            + f'value="{pov}" placeholder="auto-detect first CPU" '
            + 'hx-swap-oob="true">'
        )
        label = f" &mdash; POV: <code>{pov}</code>" if pov else ""
        return HTMLResponse(
            f'<span class="ok">&#x2713; Loaded: {p.name}{label}</span>{oob}{_render_merge_section_oob()}'
        )
    except Exception as exc:  # noqa: BLE001
        return HTMLResponse(f'<span class="err">Error: {exc}</span>')


@app.post("/generate", response_class=HTMLResponse)
async def generate(
    output_type: str = Form("dts"),
    pov: str = Form(""),
    sort: str = Form(""),
    show_clocks: Optional[str] = Form(None),
    no_timestamp: Optional[str] = Form(None),
) -> HTMLResponse:
    if state.system is None:
        return HTMLResponse('<p class="err">No system loaded.</p>')
    err, output = _do_generate(
        output_type=output_type,
        pov=pov.strip(),
        sort=sort,
        show_clocks=show_clocks is not None,
        no_timestamp=no_timestamp is not None,
    )
    if err:
        return HTMLResponse(f'<p class="err">Error: {err}</p>')
    state.last_output = output
    state.last_output_type = output_type
    sys_name = state.system.name if state.system else "output"
    filename = f"{sys_name}.{_ext(output_type)}"
    if isinstance(output, bytes):
        return HTMLResponse(
            f'<p>Binary output &mdash; {len(output):,} bytes. '
            f'<a href="/download" download="{filename}">&#x2B07; Download {filename}</a></p>'
        )
    escaped = (output or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    toolbar = (
        '<div class="output-toolbar">'
        '<button type="button" onclick="copyOutput()">&#x2398; Copy</button>'
        f'&nbsp;<a href="/download" download="{filename}">&#x2B07; {filename}</a>'
        '</div>'
    )
    return HTMLResponse(toolbar + f'<textarea id="output-text" rows="30" spellcheck="false">{escaped}</textarea>')


@app.get("/download")
def download() -> Response:
    if state.last_output is None:
        return Response("No output available.", status_code=404)
    content = (
        state.last_output if isinstance(state.last_output, bytes)
        else state.last_output.encode("utf-8")
    )
    sys_name = state.system.name if state.system else "output"
    filename = f"{sys_name}.{_ext(state.last_output_type)}"
    return Response(
        content=content,
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.post("/merge/load-hps", response_class=HTMLResponse)
async def merge_load_hps(
    hps_path: str = Form(...),
    include_dirs: str = Form(""),
) -> HTMLResponse:
    err = _do_load_hps(hps_path.strip(), include_dirs.strip())
    if err:
        return HTMLResponse(f'<p class="err">Error: {err}</p>' + _render_merge_html())
    return HTMLResponse(_render_merge_html())


@app.post("/merge", response_class=HTMLResponse)
async def do_merge(
    anchor_label: str = Form(""),
    fpga_anchor_label: str = Form("sopc0"),
) -> HTMLResponse:
    if state.system is None:
        return HTMLResponse('<p class="err">Load a sopcinfo/.qsys system first.</p>' + _render_merge_html())
    if state.hps_parsed is None:
        return HTMLResponse('<p class="err">Load an HPS/kernel DTS file first.</p>' + _render_merge_html())

    from dts_merge.merge import MergeError, merge_trees
    from sopc2dts_py.generators.GeneratorFactory import GeneratorFactory, GeneratorType
    from sopc2dts_py.model.boardinfo import BoardInfo

    state.merge_anchor = anchor_label.strip()
    state.fpga_anchor = fpga_anchor_label.strip()

    bi = state.boardinfo or BoardInfo()
    fpga_generator = GeneratorFactory.create_generator_for(state.system, GeneratorType.DTS)
    fpga_root = fpga_generator.get_dt_output(bi)

    try:
        state.merge_result = merge_trees(
            state.hps_parsed.root, fpga_root,
            base_anchor_label=state.merge_anchor or None,
            fpga_anchor_label=state.fpga_anchor or None,
        )
    except MergeError as exc:
        state.merge_result = None
        return HTMLResponse(f'<p class="err">Error: {exc}</p>' + _render_merge_html())

    return HTMLResponse(_render_merge_html())


@app.post("/merge/resolve", response_class=HTMLResponse)
async def merge_resolve(index: int = Form(...), choice: str = Form(...)) -> HTMLResponse:
    from dts_merge.merge import Resolution

    if state.merge_result is None:
        return HTMLResponse('<p class="err">No merge in progress.</p>' + _render_merge_html())
    try:
        state.merge_result.resolve(index, Resolution[choice.upper()])
    except Exception as exc:  # noqa: BLE001
        return HTMLResponse(f'<p class="err">Error: {exc}</p>' + _render_merge_html())
    return HTMLResponse(_render_merge_html())


@app.get("/merge/download")
def merge_download() -> Response:
    result = state.merge_result
    if result is None or result.unresolved:
        return Response("No fully-resolved merge available.", status_code=404)
    content = ("/dts-v1/;\n" + result.merged_root.to_string(0)).encode("utf-8")
    return Response(
        content=content,
        media_type="application/octet-stream",
        headers={"Content-Disposition": 'attachment; filename="merged.dts"'},
    )


@app.get("/log/stream")
async def log_stream() -> StreamingResponse:
    async def _events():
        while True:
            try:
                msg = _log_queue.get_nowait()
                yield f"data: {msg.replace(chr(10), ' ')}\n\n"
            except queue.Empty:
                await asyncio.sleep(0.25)
                yield ": keepalive\n\n"
    return StreamingResponse(
        _events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _do_load(input_path: str) -> Optional[str]:
    from sopc2dts_py.parsers import load_system, load_component_libs_in_dir
    from sopc2dts_py.model.boardinfo import BoardInfo
    import sopc2dts_py as _pkg
    p = Path(input_path)
    if not p.is_absolute() and not p.exists():
        p = Path(_pkg.__file__).parent.parent / input_path
    if not p.exists():
        return f"File not found: {input_path}"
    try:
        lib_dir = Path(_pkg.__file__).parent.parent
        load_component_libs_in_dir(lib_dir)
        state.system = load_system(str(p))
        state.system.recheck_components()
        state.prefill_input = input_path
        state.boardinfo = BoardInfo()
        state.merge_result = None  # any prior merge paired a now-replaced fpga tree
        return None
    except Exception as exc:  # noqa: BLE001
        logging.exception("Load failed: %s", input_path)
        return str(exc)


def _do_load_hps(input_path: str, include_dirs_raw: str) -> Optional[str]:
    from dts_merge.parser import DTSParseError, preprocess_and_parse
    import dts_merge as _dm
    pkg_root = Path(_dm.__file__).parent.parent

    def _resolve(raw: str) -> Path:
        rp = Path(raw)
        return rp if rp.is_absolute() or rp.exists() else pkg_root / raw

    p = _resolve(input_path)
    if not p.exists():
        return f"File not found: {input_path}"
    include_dirs = [_resolve(d.strip()) for d in include_dirs_raw.split(",") if d.strip()]
    try:
        state.hps_parsed = preprocess_and_parse(p, include_dirs)
        state.hps_path = input_path
        state.hps_include_dirs = include_dirs_raw
        state.merge_result = None
        return None
    except DTSParseError as exc:
        logging.exception("HPS DTS load failed: %s", input_path)
        return str(exc)


def _do_generate(
    output_type: str,
    pov: str,
    sort: str,
    show_clocks: bool,
    no_timestamp: bool,
) -> tuple[Optional[str], Optional[bytes | str]]:
    from sopc2dts_py.model.boardinfo import BoardInfo, SortType
    from sopc2dts_py.generators.GeneratorFactory import GeneratorFactory
    bi = state.boardinfo or BoardInfo()
    if pov:
        bi.set_pov(pov)
    if sort:
        bi.set_sort_type({
            "address": SortType.ADDRESS,
            "name":    SortType.NAME,
            "label":   SortType.LABEL,
        }.get(sort, SortType.NONE))
    bi.show_clock_tree = show_clocks
    bi.include_time = not no_timestamp
    gen_type = GeneratorFactory.get_type_by_name(output_type)
    if gen_type is None:
        return f"Unknown output type: {output_type}", None
    generator = GeneratorFactory.create_generator_for(state.system, gen_type)
    if generator is None:
        return f"No generator for: {output_type}", None
    try:
        if generator.is_text_output():
            return None, generator.get_text_output(bi)
        return None, generator.get_binary_output(bi)
    except Exception as exc:  # noqa: BLE001
        logging.exception("Generate failed")
        return str(exc), None


def _render_system_html() -> str:
    sys = state.system
    if sys is None:
        return "<p>No system loaded.</p>"
    rows = "".join(
        f"<tr><td>{c.instance_name}</td><td>{c.class_name}</td><td>{c.scd.group}</td></tr>"
        for c in sys.components
    )
    opts = [
        ("dts",         "DTS - Device Tree Source"),
        ("dtb",         "DTB - Binary (requires dtc)"),
        ("dtb-ihex8",   "DTB Intel I8Hex"),
        ("dtb-ihex32",  "DTB Intel I32Hex"),
        ("dtb-char-arr","DTB C char array"),
        ("kernel",      "Kernel CMacro headers"),
        ("uboot",       "U-Boot headers"),
        ("sopc-header", "sopc-create-header-files"),
        ("graph",       "Graphviz dot"),
    ]
    type_options = "".join(f'<option value="{v}">{l}</option>' for v, l in opts)
    return (
        f'<h2>System: <code>{sys.name}</code> &mdash; {len(sys.components)} components</h2>'
        '<details><summary>Component list</summary>'
        '<table><thead><tr><th>Instance</th><th>Class</th><th>Group</th></tr></thead>'
        f'<tbody>{rows}</tbody></table></details>'
        '<hr><h3>Generate</h3>'
        '<form hx-post="/generate" hx-target="#output-section" hx-swap="innerHTML" hx-indicator="#spinner">'
        '<div class="row"><label>Output type</label>'
        f'<select name="output_type">{type_options}</select></div>'
        '<div class="row"><label>POV component</label>'
        '<input id="pov-input" name="pov" type="text" placeholder="auto-detect first CPU"></div>'
        '<div class="row"><label>Sort</label><select name="sort">'
        '<option value="">default</option><option value="address">address</option>'
        '<option value="name">name</option><option value="label">label</option>'
        '</select></div>'
        '<div class="row"><label></label><span>'
        '<label><input type="checkbox" name="show_clocks"> show clocks</label>'
        ' &nbsp; '
        '<label><input type="checkbox" name="no_timestamp"> no timestamp</label>'
        '</span></div>'
        '<div class="row"><label></label>'
        '<button type="submit">Generate</button>'
        '<span id="spinner" class="htmx-indicator"> &#x23F3; generating&hellip;</span>'
        '</div></form>'
    )


def _esc(s: str) -> str:
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def _render_merge_section_oob() -> str:
    """
    Out-of-band swap for #merge-section, piggy-backed on responses (like
    /load) that change whether a system is loaded but don't target that
    section themselves — mirrors the existing pov-input OOB swap in
    /load-board.
    """
    return f'<div id="merge-section" hx-swap-oob="true">{_render_merge_html()}</div>'


def _render_merge_html() -> str:
    if state.system is None:
        return "<p>Load a sopcinfo/.qsys system above first.</p>"

    hps_status = (
        f'<span class="ok">&#x2713; Loaded: {_esc(state.hps_path)}</span>' if state.hps_parsed
        else '<span class="dim">Not loaded.</span>'
    )
    html = (
        '<form hx-post="/merge/load-hps" hx-target="#merge-section" hx-swap="innerHTML" hx-indicator="#hps-spinner">'
        '<div class="row"><label>HPS/kernel DTS</label>'
        f'<input type="text" name="hps_path" value="{_esc(state.hps_path)}" '
        'placeholder="/path/to/socfpga_..._socdk.dts" list="hps-dts-suggestions">'
        f'<datalist id="hps-dts-suggestions"><option value="{_esc(state.hps_default)}"></datalist>'
        '<button type="submit">Load</button>'
        '<span id="hps-spinner" class="htmx-indicator">&#x23F3; loading&hellip;</span>'
        '</div>'
        '<div class="row"><label>Include dirs</label>'
        f'<input type="text" name="include_dirs" value="{_esc(state.hps_include_dirs)}" '
        'placeholder="comma-separated -I dirs for cpp (dt-bindings headers, ...)" '
        'list="hps-include-suggestions">'
        f'<datalist id="hps-include-suggestions"><option value="{_esc(state.hps_include_default)}"></datalist>'
        '</div>'
        f'<div class="row"><label></label>{hps_status}</div>'
        '</form>'
        '<hr>'
        '<form hx-post="/merge" hx-target="#merge-section" hx-swap="innerHTML" hx-indicator="#merge-spinner">'
        '<div class="row"><label>Base anchor</label>'
        f'<input type="text" name="anchor_label" value="{_esc(state.merge_anchor)}" '
        'placeholder="label in the HPS tree, e.g. soc0 (blank = HPS root)"></div>'
        '<div class="row"><label>FPGA anchor</label>'
        f'<input type="text" name="fpga_anchor_label" value="{_esc(state.fpga_anchor)}" '
        'placeholder="label inside the fpga tree, e.g. sopc0"></div>'
        '<div class="row"><label></label>'
        '<button type="submit">Compute merge</button>'
        '<span id="merge-spinner" class="htmx-indicator">&#x23F3; merging&hellip;</span>'
        '</div></form>'
        f'{_render_conflicts_html()}'
    )
    return html


def _conflict_path_display(c) -> str:
    from dts_merge.merge import ConflictKind
    if c.kind == ConflictKind.DUPLICATE_LABEL and c.base_path and c.fpga_path:
        return f"{c.label}: {c.base_path} (HPS) ↔ {c.fpga_path} (FPGA)"
    return c.path


def _render_conflicts_html() -> str:
    result = state.merge_result
    if result is None:
        return ""
    if not result.conflicts:
        return '<hr><p class="ok">&#x2713; No conflicts &mdash; merge is clean.</p>' + _render_merge_download_link()

    from dts_merge.merge import ConflictKind

    rows = []
    for i, c in enumerate(result.conflicts):
        path = _esc(_conflict_path_display(c))
        kind = c.kind.name.replace("_", " ").title()
        if c.resolved:
            rows.append(
                f'<tr><td>{kind}</td><td><code>{path}</code></td>'
                f'<td class="ok">&#x2713; kept {c.resolution.name.lower()}</td><td></td></tr>'
            )
            continue
        both_btn = (
            f'<button name="choice" value="both" type="submit">Keep both</button>'
            if c.kind in (ConflictKind.DUPLICATE_PATH, ConflictKind.DUPLICATE_LABEL) else ""
        )
        rows.append(
            f'<tr><td>{kind}</td><td><code>{path}</code></td><td class="err">unresolved</td>'
            '<td>'
            f'<form hx-post="/merge/resolve" hx-target="#merge-section" hx-swap="innerHTML" style="display:inline">'
            f'<input type="hidden" name="index" value="{i}">'
            '<button name="choice" value="base" type="submit">Keep HPS</button> '
            '<button name="choice" value="fpga" type="submit">Keep FPGA</button> '
            f'{both_btn}'
            '</form></td></tr>'
        )
    table = (
        '<hr><h3>Conflicts</h3>'
        '<table><thead><tr><th>Kind</th><th>Path</th><th>Status</th><th>Resolve</th></tr></thead>'
        f'<tbody>{"".join(rows)}</tbody></table>'
    )
    unresolved_n = len(result.unresolved)
    footer = (
        f'<p>{unresolved_n} of {len(result.conflicts)} conflict(s) unresolved.</p>'
        if unresolved_n else
        '<p class="ok">All conflicts resolved.</p>' + _render_merge_download_link()
    )
    return table + footer


def _render_merge_download_link() -> str:
    return '<p><a href="/merge/download" download="merged.dts">&#x2B07; Download merged.dts</a></p>'


_EXT_MAP: dict[str, str] = {
    "dts": "dts", "dtb": "dtb", "dtb-ihex8": "hex", "dtb-ihex32": "hex",
    "dtb-char-arr": "h", "kernel": "h", "uboot": "h", "sopc-header": "h", "graph": "dot",
}


def _ext(output_type: str) -> str:
    return _EXT_MAP.get(output_type, "bin")
