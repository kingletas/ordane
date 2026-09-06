# From nothing to a deploy

Part one installs Ordane, then touches nothing but a directory you make. Nothing reaches a network and no keys are involved.

This guide assumes you have no playbooks, no inventory, no Makefile and no Ansible experience. By the end you will have a small control plane that Ordane drives, you will have deployed something with it, and you will know what the numbers on the Health page mean and where they come from.

## Contents

**Part one, about ten minutes:**

- [What Ansible is, if you have never used it](#what-ansible-is-if-you-have-never-used-it)
- [What a control plane is](#what-a-control-plane-is)
- [Step 0: get Ordane](#step-0-get-ordane)
- [Step 1: a host](#step-1-a-host)
- [Step 2: something to run](#step-2-something-to-run)
- [Step 3: let Ordane look at it](#step-3-let-ordane-look-at-it)
- [Step 4: allow an environment](#step-4-allow-an-environment)
- [Step 5: run it](#step-5-run-it)

**Part two, when you want more than a run button:**

- [Growing it up](#growing-it-up)
- [Roles, when a playbook gets long](#roles-when-a-playbook-gets-long)
- [Passwords and secrets](#passwords-and-secrets)
- [If your control plane has a Makefile](#if-your-control-plane-has-a-makefile)
- [The four numbers everyone measures](#the-four-numbers-everyone-measures)
- [Promises you make about the service](#promises-you-make-about-the-service)
- [Looking further back than this laptop](#looking-further-back-than-this-laptop)

**Part three, the rest of what is in there:**

- [Three front ends, one engine](#three-front-ends-one-engine)
- [Making the console yours](#making-the-console-yours)
- [Trying it without doing it](#trying-it-without-doing-it)
- [When two people share an environment](#when-two-people-share-an-environment)
- [Your control plane's own checks](#your-control-planes-own-checks)
- [What actually got notified](#what-actually-got-notified)
- [A control plane you have not cloned yet](#a-control-plane-you-have-not-cloned-yet)
- [When your repository is laid out differently](#when-your-repository-is-laid-out-differently)
- [Where to go next](#where-to-go-next)

## What Ansible is, if you have never used it

Suppose you have to install a package and restart a service on twelve machines. You could ssh into each one and type it. That works, and it goes wrong in the ways typing on twelve machines goes wrong: you lose track of which ones you did, somebody else does three of them differently, and six months later nobody can say what is actually on any of them.

Ansible is the answer to that. You write down the state you want, it connects over ssh, and it makes each machine match. No agent gets installed on the far end.

Two ideas are worth having before you write anything:

You describe the end state, not the steps. You do not write "run apt install nginx". You write "nginx should be installed". The difference matters on the second run.

Running it twice is safe. That is called being idempotent, and it is the whole reason this works. The first run installs nginx; the second sees it is already there and changes nothing. So the safe move when you are unsure whether something applied is to run it again, which is the opposite of a shell script.

That is the concept. Everything below is mechanics.

## What a control plane is

Two things in a directory: **a list of machines**, and **a list of jobs you run against them**. Ansible calls the first an inventory and the second a playbook. That is the whole idea.

Ordane reads a directory like that and gives you a window onto it. It does not need the directory to be arranged any particular way, and it does not need a Makefile.

You need Ansible installed. On Ubuntu:

```bash
sudo apt install ansible
```

## Step 0: get Ordane

Ordane needs Python 3.12 or newer, GTK 4 and libadwaita. On Ubuntu 24.04 or Fedora 40 and later, the desktop already has the last two.

```bash
git clone https://github.com/kingletas/ordane && cd ordane
```

Then pick one. A wrapper in `~/bin`, which is the lightest and keeps running from the checkout:

```bash
make install
```

Or a Debian package, if you would rather it be a package your system knows about:

```bash
make deb && sudo dpkg -i dist/*.deb
```

Or a flatpak, which is the most isolated:

```bash
make flatpak
```

The flatpak is worth a sentence. It runs sandboxed, but `make`, `ansible` and `git` are executed **on the host**, not inside the sandbox, because that is where your control plane, your ssh keys and your ssh agent live. A sandboxed Ansible with no keys would be no use to anybody.

Check it worked:

```bash
ordane --version
```

## Step 1: a host

Make a directory and put one machine in it. We will use your own computer, so nothing has to be reachable over the network and no keys are involved.

```bash
mkdir -p ~/my-control-plane/inventory ~/my-control-plane/playbooks
cd ~/my-control-plane
```

```bash
echo 'my-first-host ansible_connection=local' > inventory/laptop
```

That file is an inventory. It says there is one machine, it is called `my-first-host`, and Ansible should reach it by running commands here rather than connecting anywhere. The **filename** is what Ordane will call this environment, so `inventory/laptop` gives you an environment named `laptop`.

## Step 2: something to run

A playbook is a list of tasks and the hosts to run them on. Put this in `playbooks/hello.yml`:

```yaml
- name: Say hello
  hosts: all
  gather_facts: false
  tasks:
    - name: Say it
      ansible.builtin.debug:
        msg: "Ordane ran this on {{ inventory_hostname }}"
```

The `name:` on the first line matters more than it looks. **Ordane uses it as the name of the thing you can run**, so write it as something you would want to see on a button.

## Step 3: let Ordane look at it

```bash
ordane init --repo ~/my-control-plane
```

```text
wrote ~/my-control-plane/.ordane.yml
  1 target(s) from the playbooks on disk, named by the first play in each
  environments from the inventory directories on disk

Nothing is launchable yet. Uncomment an environment under `allow`, then:
  ordane doctor --repo ~/my-control-plane
```

It read the directory, found your playbook and your inventory, and wrote one file describing what it found. That file is the only thing Ordane adds to your repository.

Run the doctor whenever something confuses you:

```bash
ordane doctor --repo ~/my-control-plane
```

It checks everything that can be checked without running anything, and tells you what to do about whatever it finds.

## Step 4: allow an environment

Open `~/my-control-plane/.ordane.yml`. Near the top:

```yaml
environments:
  # Nothing runs until a name is here, and an empty list is where this
  # starts on purpose. Uncomment one when you mean it.
  allow: []
  # Found in the inventory directories on disk:
  #   - laptop
```

Change it to:

```yaml
environments:
  allow: [laptop]
```

Until you do that, Ordane will show you everything and run nothing. Every environment reaches real machines, so an empty list is where it starts deliberately. Pointing it at a repository is always safe.

## Step 5: run it

```bash
ordane --repo ~/my-control-plane
```

The window opens. (`ordane app` is the same thing spelled out; the window is what you get when you name no command.) Go to **Actions**, find **Say hello**, press **Run…**, and it will show you the exact command before it runs anything. Press **Run**.

Or from a terminal, which does the same thing over the same engine:

```bash
ordane run hello --repo ~/my-control-plane -e laptop
```

```text
ok: [my-first-host] => {
    "msg": "Ordane ran this on my-first-host"
}

PLAY RECAP *********************************************************
my-first-host  : ok=1  changed=0  unreachable=0  failed=0

succeeded in under a second (exit 0)
1 host, 0 changed
```

That run is now in the history, permanently:

```bash
ordane runs --repo ~/my-control-plane
```

## Growing it up

You have the whole shape now. Everything else is more of it.

### Something that takes a value

Put this in `playbooks/deploy.yml`:

```yaml
- name: Put a version live
  hosts: all
  gather_facts: false
  vars:
    version: "{{ release | default('') | trim }}"
  tasks:
    - name: Refuse a release nobody named
      ansible.builtin.fail:
        msg: "release is required, as -e release=1.4.0"
      when: version | length == 0

    - name: Write it down
      ansible.builtin.copy:
        dest: /tmp/ordane-guide-version
        content: "{{ version }}\n"
        mode: "0644"

    - name: Say what is live
      ansible.builtin.debug:
        msg: "{{ inventory_hostname }} is now on {{ version }}"
```

Then tell Ordane what that value is for, by adding this to the end of `.ordane.yml`:

```yaml
targets:
  deploy:
    danger: high
    deploy: true
    confirm: type-environment-name
    params:
      release:
        required: true
        help: the version to put live, such as 1.4.0
```

Now the launch form asks for a release, says what it is for, refuses to run without it, and makes you type the environment name first because you marked it dangerous:

```bash
ordane run deploy --repo ~/my-control-plane -e laptop --set release=1.4.0
```

`deploy: true` tells Ordane this run counts as a release, which is what the delivery measures on the Health view are computed from.

> [!NOTE]
> Notice the guard inside the playbook as well as the `required:` in the config. Ordane refuses an empty parameter, and the playbook refuses one too. **A playbook should be safe to run from a terminal by somebody who has never heard of Ordane.**

### A real machine

Replace the inventory line with a host you can reach over ssh:

```text
web01 ansible_host=192.0.2.10 ansible_user=deploy
```

Nothing else changes. Ordane will read the inventory, tell you how many hosts the environment holds, and use whatever ssh configuration and keys you already have. It never asks you for a password and never stores one.

### More than one environment

A second file in `inventory/` is a second environment:

```bash
echo 'web01 ansible_host=192.0.2.10' > inventory/production
```

Add it to `allow:` only when you mean it. Ordane will refuse to launch against anything not on that list, and the doctor will tell you if you spell one wrong, which is otherwise completely silent.

### A checklist around a deploy

Right now `deploy` is a command with a warning label. What it is missing is everything a person actually holds in their head when they run it: is it safe to go, did it work, and what do I do if it did not.

That set of answers is usually called a **runbook**: the page somebody writes so the next person can do this at 3am. Ordane keeps it beside the target instead of in a wiki nobody opens:

```yaml
targets:
  deploy:
    danger: high
    owner: Platform
    reviewed: 2026-09-01
    precheck: hello
    postcheck: hello
    recovery: rollback
```

- **`precheck`** runs first, and if it fails the deploy does not happen.
- **`postcheck`** runs afterwards and tells you whether it actually worked.
- **`recovery`** is what Ordane offers when something goes wrong. It only ever offers what you named. An undo you *assume* exists is more dangerous than one that is plainly missing, because people plan around it.
- **`owner`** and **`reviewed`** are for the human question. A runbook nobody has looked at in a year gets marked `STALE`.

All four run as one sequence, and the history records them as one launch, so a week later you can see the check, the deploy and the verification together instead of three unrelated rows.

### Refusing to run at all

Some things should not be launchable even by somebody who means it:

```yaml
targets:
  deploy:
    policy:
      refs: [main]          # only from the main branch
      clean_tree: true      # not with uncommitted changes
      max_hosts: 20         # not against more hosts than you expected
```

A launch that breaks any of these is refused, and Ordane gives you **every** reason at once rather than one at a time. Fixing one thing only to be refused again is how people stop reading the reason.

`clean_tree` is the one worth having early: a deploy from a working tree with uncommitted changes is one nobody can reproduce later, including you.

> [!NOTE]
> These refusals apply in the window and in the terminal alike: `ordane run` checks them too. And they are not satisfied by absence: if `refs:` names a branch and your control plane is not a git checkout at all, the launch is refused for having no branch rather than waved through.

## Roles, when a playbook gets long

A playbook with forty tasks in it is a file nobody wants to open. A **role** is that playbook broken into a folder with a name, so it can be used more than once and read by somebody in a hurry.

```text
playbooks/
  deploy.yml
  roles/
    webserver/
      tasks/main.yml       # what it does
      handlers/main.yml    # things it restarts, only if something changed
      templates/           # config files with values filled in
      defaults/main.yml    # values it uses, that you can override
```

> [!IMPORTANT]
> **`roles/` goes beside the playbook, not at the top of the repository.** Ansible looks for a role in `roles/` next to the playbook file, then in a few system directories, and nowhere else. A `roles/` folder at the project root while your playbooks live in `playbooks/` produces `the role 'webserver' was not found`, and the error points at the line in your playbook rather than at the folder, which is the wrong place to go looking.
>
> If you want them at the root anyway, say so once and Ordane will carry it for every run:
>
> ```yaml
> ansible:
>   ANSIBLE_ROLES_PATH: roles
> ```

The playbook then gets short, which is the point:

```yaml
- name: Put a version live
  hosts: all
  roles:
    - webserver
```

Ordane reads that. The launch preview shows what a target pulls in before you run it, and it distinguishes two cases that look the same in the file:

- an `import_` is resolved before the run starts, so the preview is certain about it
- an `include_` is decided while the run goes, so the preview says so rather than pretending

That distinction is why the preview can be trusted. A listing that quietly guessed at the dynamic half would be worse than one that admits which half it cannot see.

Values that belong to a group of machines go in `group_vars/`, named after the group:

```bash
mkdir -p group_vars
echo 'app_port: 8080' > group_vars/all.yml
```

Anything in `group_vars/all.yml` is available to every host, and a file named after a group applies to that group alone. This is where most real configuration ends up.

## Passwords and secrets

Some values should not be readable in the repository. Ansible encrypts those with **vault**:

```bash
ansible-vault encrypt group_vars/production.yml
```

The file is now ciphertext, safe to commit, and the playbook uses it exactly as before. Running it needs the password.

Ordane handles that. A run that asks for a vault password stops and shows a password field, you type it, and the run continues. Three things about where that value goes:

- it goes to the running process and nowhere else, not to the history, not to the output, not to disk
- Ordane teaches its redactor the value the moment you type it, so that if Ansible echoes anything containing it, it is masked before it reaches the log
- it is never stored, so the next run asks again

Ordane will not keep a secret for you, and that is deliberate rather than unfinished. A console that stores credentials is a thing worth attacking. This one is not.

## If your control plane has a Makefile

Everything so far assumed there is no Makefile, because that is the harder case and the one most people start from. If your repository has one, Ordane drives that instead, and this is worth knowing because most established control planes do.

It reads `make help` and takes the targets from it. The convention is a comment on the target line:

```makefile
.PHONY: deploy
deploy: ## Put a release live
	@ansible-playbook -i inventory/$(environment) playbooks/deploy.yml -e release=$(release)

.PHONY: help
help:
	@grep -hE '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  %-18s %s\n", $$1, $$2}'
```

Ordane runs `make help`, sees `deploy` with its description, and offers it. The description on that line is what you read in the window, so it is worth writing properly.

Which shape you have changes nothing else. The same environments, the same launch form, the same policy refusals, the same history. `examples/fleet` in this repository is deliberately both: the same playbooks and the same fourteen containers, run through a Makefile and run directly, so you can see that neither is a second-class path.

> [!NOTE]
> If `make help` exists but prints nothing Ordane can parse, the doctor says so and names the convention it looked for. A Makefile that Ordane cannot read is a Makefile that still works fine from your terminal.

## The four numbers everyone measures

Open the Health page and you will see four cards, mostly saying `Setup needed`. This is what they are.

Researchers spent years looking for what separates teams that ship well from teams that do not, and landed on four numbers. They are usually called the DORA metrics, after the group that published them. You do not need to care about the name. What matters is that they are the four questions anybody senior will eventually ask you, and most teams cannot answer any of them.

| The card | The question it answers |
|---|---|
| **Release frequency** | How often do we actually ship? |
| **Lead time for changes** | Once something is built, how long until it is live? |
| **Change failure rate** | What share of our deploys go wrong? |
| **Time to restore** | When one does go wrong, how long until it is working again? |

The first two need a **release log**: a record of what shipped and when, which your build or release process writes. Ordane reads `docs/dora/backfill.jsonl` in your control plane, or `docs/dora/history.csv` if that is what you have. It never invents one.

The last two Ordane can compute itself, **from the runs you launch through it**, once you have told it which runs count:

```yaml
targets:
  deploy:
    deploy: true      # this run is a release
    cutover: true     # and customers can see it happen
```

That is the whole connection. Mark a target `deploy: true`, run it a few times, and change failure rate starts filling in because Ordane knows which runs were releases and which of them exited non-zero. Time to restore is the gap between a deploy that failed and the next one on the same environment that worked.

You also decide which environments count, because a release to a throwaway environment should not move a real number:

```yaml
metrics:
  environments: [production]
```

> [!IMPORTANT]
> A card with no source says `Setup needed` and tells you what would fill it. It never shows a zero. That is deliberate: a zero looks like a measurement, and "we have never had a failure" and "we have never recorded anything" are very different sentences.

What Ordane cannot see. It only knows about runs launched through it. A deploy somebody did by hand in a terminal is invisible, and an outage nobody deployed through is invisible too: nothing here reads an incident tracker. Time to restore is really measuring *the deployment* being restored, not the service.

## Promises you make about the service

Below the four cards is **Service objectives**. Where the cards say what happened, an objective says what you promised: the sort of thing usually called an SLO.

Set them up in the window, or write them in `.ordane.yml`:

```yaml
slos:
  - label: Deploy succeeds without a rollback
    kind: cutover_success
    target: "95%"
    window: 90d
    environments: [production]
```

Ordane can compute two kinds itself, both from runs you marked `cutover: true`:

- `cutover_success`: what share of them worked.
- `cutover_duration`: what share finished inside a time you set with `limit_seconds`.

Anything else, it will hold for you and say so rather than guess:

```yaml
  - label: The site is up 99.9% of the month
    target: "99.9%"
    window: 28d
    blocked: needs a probe, and a probe on a laptop measures the laptop
```

> [!NOTE]
> That third one is not a failure. Writing down a promise you cannot yet measure, along with what it would take to measure it, is more useful than a number nothing computed. The alternative is a dashboard full of confident figures that nobody can trace.

## Looking further back than this laptop

Everything so far lives in files on your machine. That is the point: no server, nothing to keep running. But it means your history goes back as far as the day you started using Ordane, and it is yours alone.

The **Estate** tab is for when that is not enough: years of releases, or questions a single row cannot answer, like *which hosts has this release actually touched*. It can read two optional stores, and **either one on its own is useful**:

- a **time-series store** (InfluxDB) for figures over time, and
- a **graph store** (Neo4j) for how things connect.

Ordane never writes to either. It exports a file you load in yourself, and it only ever reads them back. So a console pointed at the wrong store cannot damage it.

Point it at them with **Point at the shared stores…**, on the rail or in the menu. What you type goes into `~/.config/ordane/stores.env`, written so only your account can read it:

```bash
ORDANE_INFLUX_URL=http://localhost:8086
ORDANE_INFLUX_TOKEN=
ORDANE_NEO4J_URL=http://localhost:7474
ORDANE_NEO4J_PASSWORD=
```

> [!TIP]
> **You do not need any of this.** No store means an Estate tab that tells you how to set one up, and every other view carries on working exactly as before. Most people never will. If you already run Grafana over an InfluxDB, this is the same InfluxDB: Ordane just queries it directly rather than drawing through Grafana.

`ordane export --format` writes the history as `csv` or `jsonl` for a spreadsheet or a script, `influx` for the time-series store, or `cypher` for the graph. Where it goes is your decision, and nothing connects on its own.

## Three front ends, one engine

The window is one way in. There are two others, and all three read the same configuration, enforce the same refusals and write to the same history.

In a browser, which is how you show somebody something without them installing anything:

```bash
ordane serve --repo ~/my-control-plane --port 8899
```

In the terminal, which is what you want over ssh or in a script. Six commands, none of which open anything:

```bash
ordane status     # the dashboard, printed here
ordane actions    # every target, grouped, with what each one asks for
ordane runs       # the history
ordane show <id>  # one run: the command, who ran it, and the tail of its output
ordane again <id> # run a recorded run again, with the same values
ordane catalog    # what Ordane parsed out of your repository, and exit
```

`ordane catalog` is the one to reach for when Ordane and you disagree about what is in your repository. It prints exactly what it understood and changes nothing.

`ordane again` is worth knowing before you need it. A run that failed at 3am gets repeated with the values it had, rather than reconstructed from memory by somebody reading scrollback.

## Making the console yours

A Makefile has targets nobody wants on a button. Leave them out:

```yaml
hidden: [help, install, test]
```

And a flat list of twenty targets is a list nobody reads. Group them the way you think about them:

```yaml
groups:
  Release: [build, deploy, activate]
  Site state: [maintenance-on, maintenance-off]
  Checks: [check, ping]
```

That is what `ordane actions` prints under headings, and what the window uses down the side. Anything you do not put in a group still appears; grouping is not a filter.

If your Makefile recipe could call anything, tell Ordane which playbook it really runs, so the preview can show the composition:

```yaml
targets:
  deploy:
    playbook: playbooks/deploy.yml
```

And if the runbook already exists somewhere, link it rather than retyping it:

```yaml
    docs: https://wiki.internal/runbooks/deploy
```

## Trying it without doing it

Ansible can run in check mode: it works out what it *would* change and changes nothing. Turn the switch on for a target and the launch form offers it:

```yaml
targets:
  deploy:
    dry_run: true
```

```bash
ordane run deploy --repo ~/my-control-plane -e laptop --check
```

Worth doing on anything marked `danger: high` before the real one. It is also the answer to *has somebody changed this machine behind my back*, since a check run against a machine that already matches reports nothing to do.

## When two people share an environment

Two deploys to the same fleet at the same time is the outage nobody plans for. Ordane holds a lock while a run is going:

```yaml
lock: target
```

- `target` lets two people run **different** things against one environment at once, and stops two of the same.
- `environment` lets neither. One run per environment, whatever it is.

Pick `environment` if you are not sure. The lock is held in the control plane itself, so it works across the window, the browser and the terminal, and it is released when the run ends however it ends.

## Your control plane's own checks

Most control planes accumulate a way of checking themselves: playbooks parse, the inventory reads, the roles resolve. Usually it lives in someone's shell history.

Write it down and Ordane will run it in a container, so it does not matter what is installed on the machine you happen to be at:

```yaml
validation:
  engine: docker
  image: python:3.12-slim
  checks:
    - name: Playbooks parse
      run: ansible-playbook --syntax-check playbooks/deploy.yml
    - name: Inventory reads
      run: ansible-inventory -i inventory/laptop --list
```

```bash
ordane checks --repo ~/my-control-plane
```

Then make a dangerous target refuse to run until they pass:

```yaml
targets:
  deploy:
    validate: true
```

That runs the check suite before the precheck, which is before the deploy. A syntax error stops being something you discover halfway through a rollout.

## What actually got notified

Your playbook probably tells Slack or PagerDuty when something ships. **Credentials for that belong in the playbook**, not here, and Ordane never asks for them.

What Ordane can do is stop the result getting lost. Name the task that reports what landed:

```yaml
notifications:
  task: Report which notifications landed
```

The console reads that task's output back and shows it beside the run, instead of leaving it four hundred lines up. It also names the one that did not land, which is the case you care about.

## A control plane you have not cloned yet

You can point Ordane at a git URL and let it do the checkout:

```bash
ordane clone https://github.com/you/control-plane --into ~/planes
ordane refs --repo ~/planes/control-plane      # every branch and tag
ordane use release-2026-09 --repo ~/planes/control-plane
```

> [!WARNING]
> Switching a ref can change what is launchable, because the branch carries its own `.ordane.yml` and its `allow:` list may be longer than the one you were on. Ordane tells you when a switch does that. It is worth reading rather than clicking past.

## When your repository is laid out differently

Everything so far assumed Ordane's guesses were right. They usually are, and when they are not you say so once rather than rearranging your repository to suit a tool.

Give the control plane a name. Without one it is taken from the git remote, and failing that from the folder, so two people can end up with two names for the same thing in a shared history:

```yaml
control_plane: you/control-plane
```

Say which way runs are driven, if you have both a Makefile and playbooks and Ordane picked the wrong one:

```yaml
driver: make        # or `ansible`. Omit it and the repository decides.
```

Say which files are playbooks, when they are not where Ordane looked:

```yaml
playbooks: [actions/*.yml, deploy/*.yml]
```

Say what your Makefile calls the environment, because not everybody calls it `environment`:

```yaml
environment_var: env
```

Say how a playbook is actually run, if it goes through a wrapper of your own. `{playbook}`, `{environment}`, `{group}` and `{module}` are filled in, and everything else is passed through untouched:

```yaml
playbook_command: [bin/run-playbook, "{playbook}"]
ansible_command: [ansible-playbook, -i, "inventory/{environment}", "{playbook}"]
ansible_probe_command: [ansible, "{group}", -i, "inventory/{environment}", -m, "{module}"]
```

The last one is for read-only questions: `ansible`, not `ansible-playbook`, because asking a host something has no playbook.

> [!TIP]
> `ordane catalog` prints what Ordane understood. If one of these is wrong, that is where you will see it, and `ordane doctor` will usually have said so first.

## Where to go next

- **[The user guide](user-guide.md)**: every view and every key.
- **[Configuration](configuration.md)**: `.ordane.yml` key by key, and [`examples/ordane.full.yml`](../examples/ordane.full.yml) has every one of them in a single annotated file.
- **[The fleet example](../examples/fleet/README.md)**: fourteen containers, two environments, and a deploy that really moves an artefact between them. It runs with a Makefile and without one, on the same playbooks.
- **[The demo](../examples/control-plane/README.md)**: a control plane that reaches nothing, so every button is safe to press. `make demo` opens it.
