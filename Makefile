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

# Windows venv uses Scripts\, Unix uses bin/
ifeq ($(OS),Windows_NT)
    BIN     := $(VENV)/Scripts
    PYTHON  := python
else
    BIN     := $(VENV)/bin
endif

PIP         := $(BIN)/pip
SETUP_STAMP := $(VENV)/.setup_complete

SOPC2DTS  := submodules/sopc2dts
DTS_MERGE := submodules/dts-merge
GUI_APP   := web.gui.app:app
GUI_HOST  := 127.0.0.1
GUI_PORT  := 8765

.DEFAULT_GOAL := dev

# ---------------------------------------------------------------------------
# Default
# ---------------------------------------------------------------------------
.PHONY: dev
dev: update-sm setup gui  ## (default) Update submodules, install deps, launch GUI

# ---------------------------------------------------------------------------
# Help
# ---------------------------------------------------------------------------
.PHONY: help
help:  ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*?##' $(MAKEFILE_LIST) | \
	  awk 'BEGIN {FS = ":.*?## "}; {printf "  %-14s %s\n", $$1, $$2}'

# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------
.PHONY: setup
setup: $(SETUP_STAMP)  ## Create venv and install all deps

$(SETUP_STAMP):
	$(PYTHON) -m venv $(VENV)
	$(BIN)/python -m pip install --upgrade pip
	$(PIP) install -e "$(SOPC2DTS)[dev]"
	# --no-deps: dts-merge depends on sopc2dts via a git URL; the sibling
	# submodule above is already installed editable, so skip re-resolving it.
	$(PIP) install -e "$(DTS_MERGE)[dev]" --no-deps
	$(PIP) install fastapi uvicorn[standard] jinja2 python-multipart
	$(PIP) install httpx2  # required by fastapi.testclient.TestClient (web/gui route tests)
	@touch $(SETUP_STAMP)
	@echo "Setup complete."

# ---------------------------------------------------------------------------
# GUI
# ---------------------------------------------------------------------------
.PHONY: gui
gui: $(SETUP_STAMP)  ## Start the web GUI (auto-opens browser)
	PYTHONPATH=. $(BIN)/python -c "from web.gui.launcher import launch; launch()"

# ---------------------------------------------------------------------------
# sopc2dts / dts-merge
# ---------------------------------------------------------------------------
.PHONY: test
test: $(SETUP_STAMP)  ## Run all submodule test suites
	PYTHONPATH=. $(BIN)/pytest -v

.PHONY: lint
lint: $(SETUP_STAMP)  ## Lint sopc2dts and dts-merge with ruff
	$(BIN)/ruff check $(SOPC2DTS)/sopc2dts_py
	$(BIN)/ruff check $(DTS_MERGE)/dts_merge

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
	  $(DTS_MERGE)/dist $(DTS_MERGE)/build \
	  $(DTS_MERGE)/*.egg-info $(DTS_MERGE)/.pytest_cache \
	  __pycache__ web/__pycache__ web/gui/__pycache__
