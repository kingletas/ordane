# A control plane that reaches nothing.
#
# Every target here prints what a real one would do and exits. It exists so the
# console can be driven — opened, searched, launched, watched, recorded —
# without a fleet, and so a repository adopting the console has a working
# `make help` to copy.
#
# The console reads the `help` output below and nothing else. The shape of that
# output is the whole contract: an `Environments` block, a `Targets` block, and
# `  name: description` at two spaces of indent.

SHELL       := /usr/bin/env bash
.SHELLFLAGS := -eu -o pipefail -c
.DEFAULT_GOAL := help

environment ?=
branch_name ?= main
release ?=
patch ?=
state ?= present
EXTRA ?=

.PHONY: help
help:
	@echo "Usage: make <target> environment=<env> [branch_name=...]"
	@echo
	@echo "Environments (a directory under inventory/):"
	@echo "  docker"
	@echo "  staging"
	@echo "  performance  (no inventory -- unusable)"
	@echo
	@echo "Targets:"
	@echo "  check: read the playbooks and the inventory, reaching nothing"
	@echo "  build: make a release artefact and put it somewhere the fleet can fetch it"
	@echo "  deploy: build a release and put it live in one go"
	@echo "  activate: switch the fleet onto a release that already exists (needs release=)"
	@echo "  maintenance-on: show the holding page and stop serving traffic"
	@echo "  maintenance-off: start serving again and take the holding page down"
	@echo "  flush-cache: empty the cache on every host that serves"
	@echo "  patch-fleet: put a patch on the fleet, or take one off"
	@echo "  ping: ask each host whether it is there"
	@echo "  slow-ping: the same, but slow enough to watch the output arrive"
	@echo "  fail-on-purpose: fails, so the failure view has something in it"
	@echo
	@echo "Shortcuts: stage (staging)"

# --- the plausible ones ---

.PHONY: check
check:
	@echo "PLAY [check] $(shell printf '%.0s*' {1..46})"
	@echo "ok: [localhost]"
	@$(MAKE) --no-print-directory recap OK=1

.PHONY: build
build:
	@echo "building $(branch_name) for $(environment)"
	@$(MAKE) --no-print-directory recap OK=2 CHANGED=1

.PHONY: deploy
deploy:
	@echo "deploying $(branch_name) to $(environment) $(EXTRA)"
	@$(MAKE) --no-print-directory notifications
	@$(MAKE) --no-print-directory recap OK=4 CHANGED=2

# The shape a real deploy prints: every notification is `failed_when: false`,
# so the playbook says out loud which of them landed. Noibu is left failing on
# purpose — a webhook that never arrives costs the deploy nothing, and that is
# exactly why nobody notices it.
.PHONY: notifications
notifications:
	@echo "TASK [Report which notifications landed] ****************************************"
	@echo "ok: [localhost] => {"
	@echo "    \"msg\": {"
	@echo "        \"newrelic\": \"0 of 3 apps FAILED\","
	@echo "        \"noibu\": \"FAILED - status 502\","
	@echo "        \"pagerduty\": \"ok\""
	@echo "    }"
	@echo "}"

.PHONY: activate
activate:
	@test -n "$(release)" || { echo "release= is required"; exit 2; }
	@echo "cutting $(environment) over to $(release)"
	@$(MAKE) --no-print-directory recap OK=6 CHANGED=3

.PHONY: maintenance-on maintenance-off flush-cache
maintenance-on maintenance-off flush-cache:
	@echo "$@ on $(environment)"
	@$(MAKE) --no-print-directory recap OK=2 CHANGED=1

.PHONY: patch-fleet
patch-fleet:
	@echo "patch $(patch) -> $(state) on $(environment)"
	@$(MAKE) --no-print-directory recap OK=2 CHANGED=1

.PHONY: ping
ping:
	@echo "web01 | SUCCESS => {\"ping\": \"pong\"}"
	@$(MAKE) --no-print-directory recap OK=1

# --- the ones that exist to be watched ---

.PHONY: slow-ping
slow-ping:
	@for host in web01 web02 admin01 cron01; do \
		echo "$$host | SUCCESS => {\"ping\": \"pong\"}"; sleep 1; \
	done
	@$(MAKE) --no-print-directory recap OK=4

.PHONY: fail-on-purpose
fail-on-purpose:
	@echo "TASK [deploy : copy the release] $(shell printf '%.0s*' {1..33})"
	@echo "fatal: [web02]: FAILED! => {\"msg\": \"No space left on device\"}"
	@echo
	@echo "PLAY RECAP $(shell printf '%.0s*' {1..58})"
	@echo "web01 : ok=3 changed=1 unreachable=0 failed=0 skipped=0"
	@echo "web02 : ok=1 changed=0 unreachable=0 failed=1 skipped=0"
	@exit 2

# --- the recap every real playbook ends with ---

OK ?= 0
CHANGED ?= 0

.PHONY: recap
recap:
	@echo
	@echo "PLAY RECAP $(shell printf '%.0s*' {1..58})"
	@echo "web01 : ok=$(OK) changed=$(CHANGED) unreachable=0 failed=0 skipped=0"
