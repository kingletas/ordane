# Examples

A recipe for each thing people actually do with Ordane, from the first run to a control plane that carries its own runbooks.

The commands here are the terminal ones, because a page can show them. Everything in the first section is also a click in the desktop console, and the [user guide](user-guide.md) is where each view is described. The two front ends read the same catalogue, the same configuration and the same history, so neither can tell you something the other would contradict.

Every recipe below was run against the two control planes that ship with Ordane: [`examples/control-plane`](../examples/control-plane), which reaches nothing, and [`examples/fleet`](../examples/fleet), whose runs reach fourteen containers and change them.

## Contents

- [Everyday recipes](#everyday-recipes)
    - [See the console with a history in it](#see-the-console-with-a-history-in-it)
    - [Drive a fleet whose runs really change something](#drive-a-fleet-whose-runs-really-change-something)
    - [Point it at your own control plane](#point-it-at-your-own-control-plane)
    - [Let it reach an environment](#let-it-reach-an-environment)
    - [See what you can run](#see-what-you-can-run)
    - [Run one thing, and watch it](#run-one-thing-and-watch-it)
    - [Rehearse without changing anything](#rehearse-without-changing-anything)
    - [Read what has run](#read-what-has-run)
    - [Run something again](#run-something-again)
    - [Ask an environment whether its hosts are there](#ask-an-environment-whether-its-hosts-are-there)
    - [The dashboard, in this terminal](#the-dashboard-in-this-terminal)
    - [When something is wrong](#when-something-is-wrong)
    - [Work from another branch](#work-from-another-branch)
    - [Start from a repository you haven't cloned](#start-from-a-repository-you-havent-cloned)
    - [Let the control plane check itself](#let-the-control-plane-check-itself)
    - [Open it in a browser](#open-it-in-a-browser)
    - [Send the history somewhere else](#send-the-history-somewhere-else)
- [Giving a control plane its own console](#giving-a-control-plane-its-own-console)
    - [Where a target comes from](#where-a-target-comes-from)
    - [Group them, and hide what nobody needs a button for](#group-them-and-hide-what-nobody-needs-a-button-for)
    - [Parameters people can't get wrong](#parameters-people-cant-get-wrong)
    - [Danger, and making someone type the name](#danger-and-making-someone-type-the-name)
    - [A runbook instead of a command](#a-runbook-instead-of-a-command)
    - [Which runs count as releases](#which-runs-count-as-releases)
    - [What a run told the outside world](#what-a-run-told-the-outside-world)
    - [Checks the control plane runs against itself](#checks-the-control-plane-runs-against-itself)
    - [Ansible settings, with no ansible.cfg](#ansible-settings-with-no-ansiblecfg)
    - [Objectives, including one that can't be measured yet](#objectives-including-one-that-cant-be-measured-yet)
    - [No Makefile at all](#no-makefile-at-all)
- [Scripting Ordane](#scripting-ordane)
    - [Exit codes and unattended runs](#exit-codes-and-unattended-runs)
    - [One command inside a script](#one-command-inside-a-script)
    - [A weekly export into a store](#a-weekly-export-into-a-store)
    - [Look at another control plane without switching](#look-at-another-control-plane-without-switching)

## Everyday recipes

### See the console with a history in it

```bash
make demo
```

It seeds ninety days of deploys, two of which failed, then opens the console against a control plane that reaches nothing. Every button works and nothing leaves your machine. The seeded history lives in `.demo-state/` and is rebuilt each time, so nothing you deploy with is touched.

### Drive a fleet whose runs really change something

Fourteen containers standing in for edges, an API tier, transcoders, a queue and a database:

```bash
docker compose -f examples/fleet/docker-compose.yml up -d
```

Ansible reaches them through `community.docker`, so there's no sshd and no key to trust:

```bash
ansible-galaxy collection install community.docker
```

Then deploy to the staging half of it:

```bash
ordane run deploy --repo examples/fleet -e staging --set release_tag=2026.09.11
```

The run builds on a transcoder, ships to the serving tier and activates one host at a time. It ends with what it did:

```text
succeeded in 9s (exit 0)
3 hosts, 5 changed
```

`changed=2` on a host means two files actually moved. `ordane run verify --repo examples/fleet -e staging` reads back what each serving host is on and asserts they agree. When you're done:

```bash
docker compose -f examples/fleet/docker-compose.yml down
```

### Point it at your own control plane

Ordane writes one file into your repository, its own configuration, and reads everything else:

```bash
ordane init --repo ~/control-plane
```

It tells you what it found and what's left to decide:

```text
wrote /home/you/control-plane/.ordane.yml
  2 target(s) from the `## description` comments in the Makefile
  environments from the inventory directories on disk

Nothing is launchable yet. Uncomment an environment under `allow`, then:
  ordane doctor --repo /home/you/control-plane
```

Then ask it what it thinks of the repository:

```bash
ordane doctor --repo ~/control-plane
```

`doctor` names which source answered for the targets and the environments, which matters: a console that assigns `environment=` to a Makefile reading `$(env)` fails silently, because the run simply goes to the default.

### Let it reach an environment

A control plane Ordane has never been configured for is read-only, and that's deliberate rather than a step somebody forgot. One line decides it:

```yaml
# .ordane.yml
environments:
  allow: [dev]
```

In the desktop console the same line is written by **Manage environments…**, which lists what was found, says which ones can't be used and why, and leaves every comment in the file where it was.

An environment with no inventory on disk is listed as unusable rather than hidden:

```text
Environments (a directory under inventory/):
  docker
  staging
  performance  (no inventory -- unusable)
```

### See what you can run

```bash
ordane actions --repo examples/control-plane
```

Every target, in the groups your configuration declares, with its parameters and what each is for:

```text
Release
───────
  build                    [changes the hosts] make a release artefact and put it somewhere the fleet can fetch it
      branch_name (optional)
  deploy                   [customers see this] build a release and put it live in one go
      branch_name (optional): the branch to build and deploy
```

`changes the hosts` and `customers see this` are the only two labels. A target that just reads state carries neither, because a label on everything is a label on nothing.

### Run one thing, and watch it

```bash
ordane run ping --repo examples/control-plane -e docker
```

The command comes first, then the output as it arrives, then what it amounted to:

```text
make ping environment=docker
run 20260911T232654Z-70dade
...
succeeded in under a second (exit 0)
1 host, 0 changed
```

### Rehearse without changing anything

Where a target declares `dry_run: true`, `--check` is offered:

```bash
ordane run deploy --repo examples/control-plane -e staging --check
```

The first line shows exactly what that turns into, so there's no guessing about whether the flag arrived:

```text
make deploy environment=staging EXTRA=--check
```

### Read what has run

```bash
ordane runs --repo examples/control-plane -n 5
ordane show last --repo examples/control-plane --tail 20
```

`show` leads with the result, the exact command, who ran it and how long it took, then the per-host recap, then the tail of the output. `--tail 0` leaves the output out entirely.

### Run something again

```bash
ordane again last --repo examples/control-plane
ordane again last --repo examples/control-plane --failed-hosts
```

The command comes from what the run recorded, not from rebuilding it. Two cases are refused rather than guessed at: a run whose command carried a secret, because what was written down isn't what ran, and a `make`-driven run handed a host limit its wrapper might ignore.

### Ask an environment whether its hosts are there

In the console, **Ask its hosts** beside a usable environment runs `ansible <group> -i <inventory> -m ping`. Only `ping`, `setup` and `gather_facts` can be asked, and none of them changes a host. `command` and `shell` are deliberately missing: anything that changes a host stays behind a declared target, where the danger label, the confirmation and the record all apply.

The probe is recorded like any other run and labelled as neither a deploy nor a cutover, so it can't move a delivery measure.

### The dashboard, in this terminal

```bash
ordane status --repo examples/control-plane
```

The four delivery measures, the objectives and the environments. A measure with no source says what would turn it on instead of printing a zero:

```text
  Change failure rate        0%            0 of 1 recorded deploy runs failed (console runs only)
  Time to restore            setup needed  A deploy run that failed, and a later one that succeeded.
```

### When something is wrong

```bash
ordane doctor --repo ~/control-plane
```

It ends with a verdict rather than a list, and each line says what to do:

```text
Usable, with 1 thing worth fixing — /home/you/control-plane
```

### Work from another branch

```bash
ordane refs --repo ~/control-plane
ordane use release/2026.09 --repo ~/control-plane
```

`refs` prints every branch and tag with its date and subject, and marks the one checked out. Switching refs is recorded as a decision, because what this console will deploy just changed.

### Start from a repository you haven't cloned

```bash
ordane clone https://github.com/you/control-plane.git --into ~/src
```

It clones, says where it landed, and that folder is what you point `--repo` at.

### Let the control plane check itself

```bash
ordane checks --repo examples/control-plane
```

Each check named in `.ordane.yml` runs in a container, read-only, with no network, as you rather than root:

```text
3 check(s) in python:3.12-slim
ok       0.5s  The Makefile is where the console looks
ok       0.6s  Every playbook is readable
ok       0.5s  No inventory holds a password

3 of 3 passed  ·  recorded as 20260911T233200Z-ce0e01
```

A check that needs to write to the repository or reach a host isn't a check, which is why it gets neither.

### Open it in a browser

```bash
ordane serve --repo ~/control-plane --port 8791
```

It binds `127.0.0.1` and nothing else. Same engine, same history; see [SECURITY.md](../SECURITY.md) for what that does and doesn't protect.

### Send the history somewhere else

```bash
ordane export --repo ~/control-plane --format jsonl -o runs.jsonl
ordane export --repo ~/control-plane --format csv    -o runs.csv
```

`influx` and `cypher` are there too, for a time-series database and a graph store. The export says what it couldn't cover rather than quietly leaving it out:

```text
  note: releases came from docs/dora/history.csv, which carries less than the event log
  note: no patch ledger at patches/ledger.jsonl
wrote 4 run(s) and 26 release(s) to runs.jsonl: one JSON object per run
```

## Giving a control plane its own console

Everything above works with no configuration beyond one allowed environment. This section is what a repository adds so the console knows what its targets mean. It all lives in `.ordane.yml`, next to the Makefile, and it's read at every refresh.

### Where a target comes from

The console never keeps a registry. A target appears because your Makefile describes it:

```makefile
.PHONY: deploy
deploy: ## build a release and put it live in one go
	@ansible-playbook -i inventory/$(environment) playbooks/deploy.yml
```

Three sources are tried in order, and the first to answer wins: the `Targets:` block `make help` prints, the two columns any `grep '## '` help target prints, and `target: ## description` lines in the Makefile itself. So a repository with no `help` target still works. `ordane doctor` says which one answered.

### Group them, and hide what nobody needs a button for

```yaml
groups:
  Release: [build, deploy, activate]
  Site state: [maintenance-on, maintenance-off]
  Fleet: [ping, slow-ping]

hidden:
  - help
```

The order you declare is the order the console shows, because that order says something about how the work is done. Nothing sorts it alphabetically.

### Parameters people can't get wrong

```yaml
targets:
  patch-fleet:
    params:
      patch:
        required: true
        choices_from: patches          # every patches/*.patch
        help: a patch file under patches/
      state:
        required: true
        choices: [present, absent]
        help: whether the patch should end up applied or removed
```

`patch=` is read back by a shell on the host, so its value may only come from the list the console controls: `allow_other` is left off on purpose. Where a free value is fine, `allow_other: true` lets someone type one, and that's a security decision rather than a convenience: several make variables reach a shell on a remote host. A value containing a shell metacharacter is refused whatever the choices say. `choices_from: glob:releases/*` reads a directory instead, and `secret: true` types a value without showing it and keeps it out of the preview, the history and the stored parameters.

A parameter that's required and missing stops before anything runs:

```text
ordane: release is required
```

### Danger, and making someone type the name

```yaml
targets:
  activate:
    danger: high
    confirm: type-environment-name
```

`danger: high` puts a warning in front of the form and makes the Run button destructive. `confirm: type-environment-name` asks for the environment's name first, in the console and in the terminal alike:

```text
make activate environment=staging release=2026.09.11
Run activate against staging? type the environment name:
```

### A runbook instead of a command

A target says what runs. A runbook says who owns it, what has to be true first, what proves it worked and what to reach for when it didn't:

```yaml
targets:
  deploy:
    danger: high
    owner: platform
    reviewed: 2026-08-01
    docs: docs/runbooks/deploy.md
    playbook: actions/deploy.yml
    precheck: check
    postcheck: verify
    recovery: maintenance-off
    policy:
      max_hosts: 20
      refs: [main, "release/*"]
      clean_tree: true
```

The precheck goes first, and a failure stops the deploy happening. A failed deploy doesn't run its postcheck, because a postcheck exists to prove a change worked, and asking it about one that never happened reports the same failure twice; you're offered the recovery instead. The policy gives you every reason it refused at once, since fixing one thing only to be refused again is how people stop reading the reason.

None of it is inferred. A precheck nobody named doesn't run, and a recovery nobody wrote isn't offered: an undo you assume exists is more dangerous than one that's plainly missing.

### Which runs count as releases

```yaml
targets:
  deploy:
    deploy: true
    cutover: true

metrics:
  environments: [production]
```

Without that last block, a run against a throwaway container fleet would read as a release and move a number that's meant to mean something. The checks inside a runbook are recorded under their own kinds and carry no labels, so a precheck can never move a measure either.

### What a run told the outside world

A deploy that opens a maintenance window, marks a release and posts a webhook usually does all of it with `failed_when: false`, so a webhook that never landed costs the deploy nothing and stays invisible. The playbook already knows which landed; name that task and the run reads it back:

```yaml
notifications:
  task: Report which notifications landed
```

The run then carries a panel reading *2 of 3 landed*, with a `DID NOT LAND` badge on the one that missed.

### Checks the control plane runs against itself

```yaml
validation:
  image: python:3.12-slim
  checks:
    - name: The Makefile is where the console looks
      run: [test, -f, Makefile]
    - name: No inventory holds a password
      run: [python, -c, "import glob, re; assert not [f for f in glob.glob('inventory/*') if re.search('password', open(f, errors='ignore').read(), re.I)]"]
```

`ordane checks` runs them, and so does the button on the repository card.

### Ansible settings, with no ansible.cfg

Each key is an environment variable set on the run, so these add to whatever `ansible.cfg` is found rather than replacing it:

```yaml
ansible:
  ANSIBLE_ROLES_PATH: ./roles
  ANSIBLE_PYTHON_INTERPRETER: /usr/bin/python3
```

`ANSIBLE_CONFIG` is refused, because it replaces the repository's own config outright and a console setting `vault_password_file` would quietly stop decrypting. A setting whose value is a credential is refused too, since this file gets committed. `ANSIBLE_VAULT_PASSWORD_FILE` names a path, so it's fine.

### Objectives, including one that can't be measured yet

```yaml
slos:
  - label: Cutover succeeds without rollback
    kind: cutover_success
    environments: [production]
    target: "95%"
    window: 90d
  - label: Availability, planned windows excluded
    target: "99.9%"
    window: 28d
    blocked: needs a synthetic probe, which must not run on a laptop
```

The blocked one says what it's short of rather than showing a zero. A page that invents a good number is less use than one admitting a gap.

### No Makefile at all

Ordane drives `ansible-playbook` itself. The playbooks are the catalogue, named by the first play in each:

```yaml
playbooks:
  - "playbooks/*.yml"

# optional: how a bare playbook is run. {playbook} and {environment} are substituted.
playbook_command: [bin/run-playbook, "{playbook}"]
```

Try it on the fleet example, which works both ways:

```bash
mv examples/fleet/Makefile examples/fleet/Makefile.off
ordane doctor --repo examples/fleet
```

```text
✓ 5 targets were found, across 2 environments
✓ Driven by ansible-playbook
    Targets from the playbooks on disk, named by the first play in each;
    environments from the inventory directories on disk.
```

The danger labels, the parameters, the runbooks and the refusals all still apply, because they live in `.ordane.yml` rather than in the Makefile. Put it back with `mv examples/fleet/Makefile.off examples/fleet/Makefile`.

## Scripting Ordane

### Exit codes and unattended runs

Every command exits 0 when it worked and 1 when it didn't, so `&&` and `set -e` behave. A refusal is a failure: an unknown environment, a missing required parameter and a target that failed all exit 1.

A target that asks for confirmation can't be launched from a script unless you say so in advance:

```bash
ordane run deploy --repo ~/control-plane -e staging --set release_tag=2026.09.11 --yes
```

Without `--yes`, and with nothing to answer on, it cancels rather than guessing.

### One command inside a script

```bash
#!/usr/bin/env bash
# Deploy a release to staging, then prove it landed.
set -euo pipefail

repo=~/control-plane
tag="$1"

ordane run deploy --repo "$repo" -e staging --set "release_tag=$tag" --yes
ordane run verify --repo "$repo" -e staging --yes
ordane show last --repo "$repo" --tail 0
```

Every one of those runs is recorded the same way a click is, so the history doesn't have a hole in it where the automation was.

### A weekly export into a store

A line for `crontab -e`. Cron starts with an almost empty `PATH`, so give the full path:

```text
0 7 * * 1  /usr/bin/ordane export --repo /home/you/control-plane --format csv -o /home/you/reports/runs.csv
```

The export names any source it couldn't read, so a report that's missing half the picture says so in the file you're about to read.

### Look at another control plane without switching

`--repo` is per command, so nothing is switched and nothing is remembered:

```bash
ordane status --repo ~/other-control-plane
ordane runs --repo ~/other-control-plane -n 10
```

One history file serves every control plane, and each view scopes to its own, so one estate never judges another's runs.
