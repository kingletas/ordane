# The fleet, driven by make.
#
# Ordane reads the `Targets:` block below and runs these for you. Rename this
# file and it drives the playbooks directly instead; both are documented in
# README.md and neither needs the playbooks to change.

SHELL       := /usr/bin/env bash
.SHELLFLAGS := -eu -o pipefail -c
.DEFAULT_GOAL := help

environment ?=
release_tag ?=

INVENTORY = inventory/$(environment)

.PHONY: guard
guard:
	@test -n "$(environment)" || { echo "environment= is required"; exit 2; }
	@test -f "$(INVENTORY)" || { echo "no inventory at $(INVENTORY)"; exit 2; }

.PHONY: check
check: guard
	@ansible-playbook -i $(INVENTORY) playbooks/check.yml

.PHONY: deploy
deploy: guard
	@ansible-playbook -i $(INVENTORY) playbooks/deploy.yml -e release_tag=$(release_tag)

.PHONY: verify
verify: guard
	@ansible-playbook -i $(INVENTORY) playbooks/verify.yml

.PHONY: drain
drain: guard
	@ansible-playbook -i $(INVENTORY) playbooks/drain.yml

.PHONY: restore
restore: guard
	@ansible-playbook -i $(INVENTORY) playbooks/restore.yml

.PHONY: up
up:
	@docker compose up -d

.PHONY: down
down:
	@docker compose down

.PHONY: help
help:
	@echo "Environments (an inventory under inventory/):"
	@echo "  staging"
	@echo "  production"
	@echo ""
	@echo "Targets:"
	@echo "  check: ask every host in the tier whether it answers"
	@echo "  deploy: build a release, ship it to the serving tier and activate it"
	@echo "  verify: confirm every serving host is on the same release"
	@echo "  drain: take the edges out of rotation, one at a time"
	@echo "  restore: put the edges back in rotation"
	@echo "  up: start the fleet containers"
	@echo "  down: stop them"
