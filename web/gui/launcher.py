# sopc2dts - Devicetree generation for Altera systems
#
# Python port Copyright (C) 2026 Laurence <laurence@anodes4life.com>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

"""
GUI launcher — finds a free port, starts uvicorn in a background thread,
waits for the server to be ready, then opens the default browser.
"""

import socket
import threading
import time


def _find_free_port() -> int:
    """Bind to port 0 and let the OS pick a free one."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


def _wait_for_server(url: str, timeout: float = 5.0) -> bool:
    """Poll /health until the server responds or timeout expires."""
    import urllib.error
    import urllib.request

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            urllib.request.urlopen(f"{url}/health", timeout=0.5)
            return True
        except Exception:
            time.sleep(0.1)
    return False


def launch(input_file: str = "") -> None:
    """
    Start the sopc2dts web GUI, open the browser, and block until exit.

    Parameters
    ----------
    input_file:
        Optional path pre-filled from the ``-i`` CLI argument.
    """
    try:
        import uvicorn
    except ImportError:
        raise SystemExit(
            "GUI dependencies not installed.  "
            "Run: pip install 'sopc2dts[gui]'"
        )

    # Import app *after* uvicorn check so the import error is clear.
    from .app import app, state  # noqa: PLC0415

    state.prefill_input = input_file

    port = _find_free_port()
    url = f"http://127.0.0.1:{port}"

    config = uvicorn.Config(
        app,
        host="127.0.0.1",
        port=port,
        log_level="warning",
        log_config=None,  # don't let uvicorn reset our logging config
    )
    server = uvicorn.Server(config)

    # Open the browser once the server is ready — runs in a background thread
    # so the server can start in the main thread (which handles Ctrl+C properly).
    def _open_when_ready() -> None:
        if _wait_for_server(url):
            import webbrowser
            webbrowser.open(url)
            print(f"sopc2dts GUI: {url}  (Ctrl+C to exit)")
        else:
            print(f"sopc2dts GUI: server did not start in time.  Try: {url}")

    threading.Thread(target=_open_when_ready, daemon=True).start()

    # Block here — uvicorn installs its own SIGINT/SIGTERM handlers so
    # Ctrl+C shuts the server down cleanly and returns control to the shell.
    server.run()
