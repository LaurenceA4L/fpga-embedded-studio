# fpga-embedded-studio — top-level build orchestration
#
# Targets:
#   make setup       — create venv, install sopc2dts (editable) + GUI deps
#   make gui         — start the web GUI (localhost:8000)
#   make test        — run sopc2dts test suite
#   make lint        — ruff check on sopc2dts
#   make update-sm   — pull latest commits on all submodules
#   make clean       — remove venv and build artefacts

PYTHON    ?= python3
VENV      := .venv
BIN       := $(VENV)/bin
PIP       := $(BIN)/pip
UVICORN   := $(BIN)/uvicorn

SOPC2DTS  := submodules/sopc2dts
GUI_APP   := web.gui.app:app
GUI_HOST  := 127.0.0.1
GUI_PORT  := 8000

.DEFAULT_GOAL := help

# ---------------------------------------------------------------------------
# Help
# ---------------------------------------------------------------------------
.PHONY: help
help:
	@grep -E '^[a-zA-Z_-]+:.*?##' $(MAKEFILE_LIST) | \
	  awk 'BEGIN {FS = ":.*?## "}; {printf "  %-14s %s\n", $$1, $$2}'

# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------
.PHONY: setup
setup: $(VENV)/pyvenv.cfg  ## Create venv and install all deps

$(VENV)/pyvenv.cfg:
	$(PYTHON) -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -e "$(SOPC2DTS)[dev]"
	$(PIP) install fastapi uvicorn[standard] jinja2 python-multipart
	@echo "Setup complete. Activate with: source $(VENV)/bin/activate"

# ---------------------------------------------------------------------------
# GUI
# ---------------------------------------------------------------------------
.PHONY: gui
gui: $(VENV)/pyvenv.cfg  ## Start the web GUI at http://$(GUI_HOST):$(GUI_PORT)
	PYTHONPATH=. $(UVICORN) $(GUI_APP) \
	  --host $(GUI_HOST) --port $(GUI_PORT) --reload

# ---------------------------------------------------------------------------
# sopc2dts
# ---------------------------------------------------------------------------
.PHONY: test
test: $(VENV)/pyvenv.cfg  ## Run all submodule test suites
	$(BIN)/pytest -v

.PHONY: lint
lint: $(VENV)/pyvenv.cfg  ## Lint sopc2dts with ruff
	$(BIN)/ruff check $(SOPC2DTS)/sopc2dts_py

# ---------------------------------------------------------------------------
# Submodules
# ---------------------------------------------------------------------------
.PHONY: update-sm
update-sm:  ## Pull latest on all submodules
	git submodule update --remote --merge

# ---------------------------------------------------------------------------
# Clean
# ---------------------------------------------------------------------------
.PHONY: clean
clean:  ## Remove venv and build artefacts
	rm -rf $(VENV) $(SOPC2DTS)/dist $(SOPC2DTS)/build \
	  $(SOPC2DTS)/*.egg-info $(SOPC2DTS)/.pytest_cache \
	  __pycache__ web/__pycache__ web/gui/__pycache__
