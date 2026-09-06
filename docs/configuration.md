# `.ordane.yml`

Everything `make help` cannot say.

`make help` supplies the target list, the descriptions and the environments. This file carries what that output has no way to express: which environments the console may reach, what a parameter means, which targets are dangerous, and which runs count as a release.

Every key is optional. A repository with no file at all still gets a catalogue, a history and a dashboard. It just cannot launch anything.

The [example](../examples/control-plane/.ordane.yml) is a working file with every key in it, annotated. This page is the reference.

## Contents

- [driver](#driver)
- [environments](#environments)
- [groups and hidden](#groups-and-hidden)
- [targets](#targets)
- [params](#params)
- [playbooks](#playbooks)
- [metrics and slos](#metrics-and-slos)
- [ansible](#ansible)

> [!TIP]
> [`examples/ordane.full.yml`](../examples/ordane.full.yml) has every key in one file, annotated with what it decides. A test reads the loader's own source and fails if that example is missing a key, or documents one nothing reads. The second is the worse mistake, because it looks like it works.

## control_plane

```yaml
# What this control plane is called, in a history that several people read.
control_plane: you/control-plane

# What a run locks. `target` lets two people run different runbooks against one
# environment but not the same one; `environment` locks the whole environment.
lock: target
```

Without a name, a control plane is known by its folder, and two people
with different checkouts in folders of the same name would look like one
estate. The name is taken from `control_plane:` first, then from the git
remote, and only then from the folder, which the doctor reports as not
portable.

## driver

```yaml
# `make` or `ansible`. Omit it and the repository decides: a Makefile is driven
# by make, anything else by ansible-playbook.
driver: ansible

# What the ansible driver runs, if it is wrapped in a script of your own.
ansible_command: [bin/run-playbook]
```

A repository with no Makefile is driven by `ansible-playbook` directly. The targets are the playbooks your `playbooks:` globs select, each named by its first play's `name:`. A run becomes `ansible-playbook -i <inventory> <playbook>`, with parameters as `-e key=value` and a dry run as `--check`.

This file is the only one the console writes into your repository, apart from an EC2 inventory if you ask it to build one. Your playbooks are read and never edited, and anything the console needs that Ansible has no way to express lives here.

## environments

```yaml
environments:
  allow: [staging, docker]

  # Environments this file declares outright, for an inventory nothing finds.
  # The console writes these when you add one in Manage environments.
  names: [bare-metal]

  # Where an environment's inventory is. `{environment}` is substituted, and
  # `ansible-playbook` needs this when the inventories are not discovered.
  inventory: inventory/{environment}

  # Where an environment lives, when `make help` does not list them. These are
  # the defaults; name your own if the inventory is somewhere else.
  discover:
    - inventory/*
    - inventories/*
    - environments/*
```

Nothing can be launched until a name is here, and an empty list is where it starts on purpose. A name `make help` never prints matches nothing, and leaves the console read-only without explaining itself. Run `ordane doctor` and it will tell you.

The desktop console writes this list, and only this list, from **Manage environments…**. It replaces the one line and leaves every comment in the file untouched.

> A control plane with no environments gets a single stand-in called `default`. It still has to be allowed before anything runs, with `allow: [default]`, and a run against it carries no environment assignment at all. Inventing a variable your Makefile never reads would be worse than passing none.

```yaml
# The variable a target reads to know where it runs. The console assigns this
# one and nothing else.
environment_var: env
```

If your Makefile reads a different name, the value goes nowhere. `make deploy environment=prod` against a recipe using `$(env)` does not fail. Make sets a variable nothing reads, the play runs against whatever the default is, and nobody is told. `ordane init` works out the right name, and `ordane doctor` fails when it is wrong.

## groups and hidden

```yaml
groups:
  Release: [build, deploy, activate]
  Cache: [flush-cache]

hidden:
  - help
```

Groups appear in the order you declare them, in all three front ends. That order says something about how the work is done, so nothing sorts it alphabetically. A target in no group ends up in `Other`.

`hidden` takes a target out of the console without touching the Makefile. `help` lists itself, and nobody needs a button for that.

## targets

```yaml
targets:
  activate:
    danger: high
    confirm: type-environment-name
    cutover: true
    deploy: true
    dry_run: true
    params: {}
```

| Key | What it does |
|---|---|
| `danger` | `low`, `medium` or `high`. Decides the words the row carries, the warning on the form, and whether launching from a terminal asks first |
| `confirm` | `type-environment-name` makes the form refuse until the environment is typed out |
| `cutover` | This run flips a release. Counts towards the cutover objectives, and writes a `cutover.*` deployment event |
| `deploy` | This run ships something. Counts towards release risk, and writes a `build.*` deployment event |
| `dry_run` | Offers a switch that adds `EXTRA=--check` |
| `environment` | This target hardcodes its environment inside the recipe: see below |

### `environment:` on a target is not cosmetic

A shortcut like `make stage` names `staging` inside the recipe. **Without `environment: staging` here, the allow list would be checked against whatever the form submitted while the run reached somewhere else entirely.** Declare it for every target that names its own environment; the doctor fails if the name does not exist.

## params

```yaml
params:
  release:
    required: true
    help: the built release to cut over to
    choices_from: glob:releases/*
    allow_other: true
  state:
    required: true
    choices: [present, absent]
```

| Key | What it does |
|---|---|
| `required` | The form refuses to launch without it |
| `help` | One sentence saying what the value is for. **It is shown on the row**, not hidden in a tooltip |
| `choices` | A fixed list |
| `choices_from` | A list read from disk on every open: `patches`, `playbooks`, `environments`, or `glob:<pattern>` |
| `allow_other` | Whether a value outside the list is accepted at all |
| `secret` | The value is typed without being shown, masked in the command preview, and stored masked in the run history along with the parameters. It is still passed to the command that runs |

> **`allow_other` is a security decision, not a convenience.** Several make variables reach a shell on a remote host. A value outside its declared choices is refused, and a value containing a shell metacharacter is refused whatever the choices say. Leave `allow_other` off wherever a list can be written.

## playbooks

```yaml
playbooks:
  - "actions/*.yml"

playbook_command: [bin/run-playbook, "{playbook}"]
```

Which files count as a playbook, and how a bare one is run. `{playbook}` and `{environment}` are substituted; every other element is passed through as it is written.

## metrics and slos

```yaml
metrics:
  environments: [production]

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

`metrics.environments` decides which environments count as a release. Leave it out and only `production` counts. Every measure honours it, so a release to a throwaway container fleet never moves a delivery number.

An objective with `kind: cutover_success` or `cutover_duration` is computed from the runs this console recorded. **One with neither is declared unmeasurable, and `blocked:` is where you say what it would take.** That is not a placeholder to be filled in later with a plausible figure: an objective reporting a number it cannot source is worse than one admitting it has none.

## ansible

This is how you configure Ansible itself when your control plane has no `ansible.cfg`. Every key is an environment variable name, and each one is set on the run's environment rather than written into a file.

```yaml
ansible:
  ANSIBLE_ROLES_PATH: ./roles
  ANSIBLE_INVENTORY_ENABLED: host_list,script,yaml,ini
  ANSIBLE_TIMEOUT: 60
```

These add to a repository's `ansible.cfg` instead of replacing it, so a plane with both keeps everything its own file declares and gets these on top. `ansible-config dump` reports where each value came from, printing `DEFAULT_ROLES_PATH(env: ANSIBLE_ROLES_PATH)` in the run's own output. Every applied setting is also recorded on the run beside the branch and commit, so a run that behaved differently because of one says as much.

`ANSIBLE_CONFIG` is refused. It replaces your repository's config outright instead of adding to it, so a plane whose `ansible.cfg` sets `vault_password_file` would quietly stop decrypting every vaulted variable. Declare the individual settings instead. It will also read a config out of a world-writable directory, which Ansible itself deliberately ignores.

A setting whose value is a credential is refused too, since this file gets committed. `ANSIBLE_VAULT_PASSWORD_FILE` is allowed, because it names where a password lives rather than the password itself, and it is the setting you actually want here.

The doctor will name a setting Ansible does not recognise. An unknown `ANSIBLE_*` variable is ignored silently, so a typo like `ANSIBLE_ROLESPATH` for `ANSIBLE_ROLES_PATH` never applies while everything reports that it did. The names are checked against `ansible-config list`, and if that cannot be read the doctor says so instead of passing quietly.

> `ANSIBLE_STDOUT_CALLBACK` is accepted, with a warning. Only Ansible's default callback prints a `PLAY RECAP`; `minimal`, `oneline` and `json` print none at all. Without one, the console records no hosts, no per-host counts and no failure attribution, and nothing about the run looks like an error. `ordane doctor` tells you when you have declared one.

If you have no `ansible.cfg` anywhere, the doctor tells you. A control plane with none in the repository and none in your home directory runs on Ansible's defaults: no roles path, no inventory plugins beyond the built-in ones, no vault password file. Nothing else would ever mention it.
