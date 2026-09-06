# ordane — a desktop console for an Ansible control plane, with or without a Makefile
#
# Run `make` with no arguments for the list, and `make demo` to see it working
# against a control plane that reaches nothing.

SHELL       := /usr/bin/env bash
.SHELLFLAGS := -eu -o pipefail -c
.DEFAULT_GOAL := help

PREFIX ?= $(HOME)/bin
REPO   ?= $(HOME)/control-plane
PORT   ?= 8710

.PHONY: help
help: ## Show this help
	@echo
	@echo "  ordane — a desktop console for an Ansible control plane"
	@echo
	@grep -hE '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "    \033[36m%-12s\033[0m %s\n", $$1, $$2}'
	@echo

# --- install ----------------------------------------------------------------

.PHONY: install
install: ## Copy this tool into ~/bin (PREFIX= to change)
	@scripts/install "$(PREFIX)"

.PHONY: uninstall
uninstall: ## Remove the installed copy, the desktop entry and the icon
	@rm -f "$(PREFIX)/ordane"
	@rm -f "$(HOME)/.local/share/applications/com.kingletas.Ordane.desktop"
	@rm -f "$(HOME)/.local/share/icons/hicolor/scalable/apps/com.kingletas.Ordane.svg"
	@echo "removed ordane from $(PREFIX), and its desktop entry"
	@echo "the run history in ~/.local/state/ordane was not touched"

# --- run --------------------------------------------------------------------

.PHONY: venv
venv: ## Build the virtualenv with the system GTK bindings visible
	@test -d .venv || uv venv --python /usr/bin/python3 --system-site-packages
	@uv sync

.PHONY: demo
demo: seed ## Open the console against the example control plane, which reaches nothing
	@uv run ordane app --repo examples/control-plane \
		--state-dir $(DEMO_STATE) \
		--events $(DEMO_STATE)/deployments.jsonl

# Its own state directory, rebuilt each time: the demo must never write into
# the history of a control plane somebody actually drives.
DEMO_STATE ?= .demo-state

.PHONY: seed
seed: venv ## Rebuild the demo history, so every measure and objective has a source
	@uv run python scripts/seed-demo.py $(DEMO_STATE)

.PHONY: app
app: venv ## Run the desktop app against REPO=
	@uv run ordane app --repo "$(REPO)"

.PHONY: serve
serve: ## Run the web console against REPO= on PORT=
	@uv run ordane serve --repo "$(REPO)" --port "$(PORT)"

.PHONY: status
status: ## Print the dashboard in this terminal for REPO=
	@uv run ordane status --repo "$(REPO)"

.PHONY: catalog
catalog: ## Print what the console would offer for REPO=, and exit
	@uv run ordane catalog --repo "$(REPO)"

.PHONY: doctor
doctor: ## Check REPO= and say what to do about anything found
	@uv run ordane doctor --repo "$(REPO)"

# --- packaging --------------------------------------------------------------

.PHONY: deb
deb: ## Build a .deb into dist/
	@scripts/build-deb

FLATPAK_ID  := com.kingletas.Ordane
FLATPAK_DIR ?= .flatpak-build

.PHONY: flatpak
flatpak: ## Build and install the flatpak for this user
	@command -v flatpak-builder >/dev/null || { \
		echo "  flatpak-builder is not installed:"; \
		echo "    sudo apt install flatpak-builder"; exit 1; }
	@flatpak-builder --force-clean --user --install-deps-from=flathub --install \
		"$(FLATPAK_DIR)" packaging/$(FLATPAK_ID).yml
	@echo
	@echo "  installed. Run it with:  flatpak run $(FLATPAK_ID)"

.PHONY: flatpak-uninstall
flatpak-uninstall: ## Remove the flatpak again
	@flatpak uninstall --user -y $(FLATPAK_ID) || true

# --- checks -----------------------------------------------------------------

.PHONY: lint
lint: ## Static checks
	@uv run ruff check src tests scripts
	@uv run ruff format --check src tests scripts

.PHONY: format
format: ## Apply the formatter
	@uv run ruff format src tests scripts
	@uv run ruff check --fix src tests scripts

.PHONY: test
test: ## The unit suite
	@uv run pytest -q

.PHONY: smoke
smoke: venv ## Drive the real window against the example, and save a PNG of each view
	@uv run python scripts/gui-smoke.py $(if $(REPO_SMOKE),"$(REPO_SMOKE)",)

.PHONY: metadata
metadata: ## Validate the desktop entry and its icon
	@scripts/validate-metadata

.PHONY: check
check: lint test metadata ## Everything a commit has to pass
	@echo
	@echo "  lint, tests and metadata pass"
	@echo "  make smoke drives the window; CI proves the packages install instead"

.PHONY: ci
ci: ## The gate, plus the window drive CI cannot do reliably, before you push
	@echo "=== job: lint, tests and metadata ==="
	@$(MAKE) --no-print-directory check
	@echo
	@echo "=== job: drive the window ==="
	@command -v xvfb-run >/dev/null || { \
		echo "  xvfb-run is missing. CI has it and this machine does not:"; \
		echo "    sudo apt install xvfb"; exit 1; }
	@xvfb-run -a $(MAKE) --no-print-directory smoke
	@echo
	@echo "  the gate passes and the window drew itself. CI also builds, installs"
	@echo "  and runs the deb and the flatpak, which needs a clean machine."
