# Contributing

## Running the GUI in development

```
make gui
```

The GUI log panel shows WARNING and ERROR by default. To see verbose DEBUG output
(component library loading, parser internals, etc.) change the handler level in
`web/gui/app.py`:

```python
_gui_handler.setLevel(logging.DEBUG)  # was logging.WARNING
```

Reload the server — uvicorn's `--reload` picks it up automatically when launched
via the launcher. When running directly via `make gui` the launcher does not use
`--reload`, so restart manually.

## Running tests

```
make test        # full sopc2dts suite via pytest
make lint        # ruff check on sopc2dts source
```

## Submodule workflow

```
make update-sm   # pull latest on all submodules
```

After pulling sopc2dts, re-run `make setup` if dependencies changed
(or just `make` which runs setup → gui).
