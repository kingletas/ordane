# User guide

The console replaces nothing. Where your control plane has a Makefile it reads what `make help` already prints and runs `make` for you; where it does not, your playbooks are the catalogue and it runs `ansible-playbook` directly. Either way it shows you the command first, streams the output, and keeps a record of every run. That last part is the one you never had before.

Everything described here is also available in the terminal and in a browser, over the same catalogue, configuration, measures and history. No front end can tell you something another one would contradict.

## Contents

- [The rail and the stage](#the-rail-and-the-stage)
- [Overview](#overview)
- [Actions](#actions)
- [Runs](#runs)
- [Environments](#environments)
- [Delivery](#delivery)
- [Setup](#setup)
- [The command palette](#the-command-palette)
- [What a run told the outside world](#what-a-run-told-the-outside-world)
- [Watching a run](#watching-a-run)
- [Keyboard shortcuts](#keyboard-shortcuts)
- [What a playbook is made of](#what-a-playbook-is-made-of)
- [What an environment is made of](#what-an-environment-is-made-of)
- [Checks a control plane runs against itself](#checks-a-control-plane-runs-against-itself)
- [A control plane that lives on GitHub](#a-control-plane-that-lives-on-github)
- [When nothing can be launched](#when-nothing-can-be-launched)
- [When something is wrong](#when-something-is-wrong)

## The rail and the stage

The window is a dark rail down the left and a stage beside it. **The rail holds places and nothing else.** Everything you can do *to* a repository — re-read it, open its configuration, export its history, check it, open another — is on the repository card at the foot of the rail, and in the command palette.

At the top of the stage is the place you are in, what it is about, and four things: the command palette (`Ctrl+K`), re-read the repository (`Ctrl+R`), the main menu, and the window controls.

The card at the foot of the rail tells you which control plane this window is driving: its name, the branch, whether the working tree is clean, and how old the reading is. A deploy from a dirty tree is one nobody can reproduce, and the branch is the difference between shipping what was reviewed and shipping whatever happens to be checked out. Click the card for everything the repository can be asked to do.

The mouse's side buttons step back and forward through the places you have visited, the way they do everywhere else on this desktop. `Alt+Left` and `Alt+Right` do the same.

You can select and copy values in a run: the command, the exit code, and whatever a host printed when it failed. The output pane is a plain text view, so select it, right-click it, `Ctrl+C` it.

`Ctrl+B` shows and hides the rail, and a window narrower than 1000 px folds it away for you.

## The six places

| Place | What it answers |
|---|---|
| **Overview** | Is it safe to act, and is there anything I should know about? |
| **Actions** | What can I run, and what will it do? |
| **Runs** | What has run, how did it go, and what is one run made of? |
| **Environments** | What can be reached, and what is the one that cannot waiting on? |
| **Estate** | What the shared stores know that this machine does not |
| **Delivery** | How often we ship, how long it takes, and what we are holding ourselves to |

Three more screens are reached from those rather than listed beside them, because each stops being interesting once you are past it: **Setup**, **About** and **Preferences**.

## Overview

The page leads with **one sentence** saying whether it is safe to deploy, and one line naming the single thing standing in the way. Nothing else on the screen is allowed to compete with it.

Under it is the estate: one tile per environment, with a status bar down its edge, how many hosts it holds, when it last ran, and how much the last run had to change. An environment that is waiting on you gains one line saying what would fix it — in blue, because a repository that has not finished being set up has not gone wrong.

Then the instruments: the setup card while there are steps left, the two delivery measures that have a source, the objectives, and the last day of runs.

Below that, the four delivery measures, under the names the industry gave them:

| Card | What it counts |
|---|---|
| Release frequency | Releases per month, from the release history the reporter commits |
| Lead time for changes | Median time from a release being built to it reaching production |
| Change failure rate | Share of recorded deploys that failed |
| Time to restore | Median time from a deploy that failed to the next one that worked |

Two of the four come from the release log your reporter commits, and two from this console's own runs. Change failure rate counts finished deploy runs and their exit codes. Time to restore measures the gap between a failed deploy and the next one that worked on the same environment, so what it is really timing is the deployment being restored, not the service. Nothing here reads an incident tracker, which means a failure nobody deployed through is invisible to it, and a second failure before a fix does not restart the clock.

A card with no source is dormant — a dashed outline and the sentence that would turn it on. It never says `no data`, never says `Setup needed`, and never shows a zero, because a backfilled figure makes an absence look like a measurement, and a page that invents a good number is less use than one admitting a gap.

A comparison with the previous six months only appears where the sample supports it. Both halves need at least eight releases; below that an arrow would be noise pointing somewhere, and people read arrows as findings. The arrow shows what the number did and the colour says whether that is good news, so a lead time that rose points up and is amber.

Recent runs folds away, and so does the run history on the Runs page. Click the heading. Your choice is remembered between sessions, like the window size and the rail.

The objectives below follow the same rule. One with no way to be measured says what it is short of — *Needs 1 cutover*, *Needs a probe* — rather than complaining, whether what is missing is a probe that should not run on a laptop or an SLI definition nobody has written. You decide which environments count towards a measure in `.ordane.yml`; without that, a run against a throwaway container fleet would read as a release.

## Actions

Every target `make help` prints, in the groups your configuration declares and the order it declares them. That order says something about how the work is done, so nothing sorts it alphabetically.

You see one group at a time, chosen from the column on the left, which says how many targets are in each. Eleven scroll and forty do not. Searching ignores the groups and ranks every match instead, since a heading would hide which one is actually the best.

A target that changes something says so in words. `Changes the hosts` and `Customers see this` are the two labels, and a target that only reads state carries neither. A label on everything is a label on nothing.

Right-click a row to copy the `make` command it would run, or to open the form. Click **Run…** and you get a form with:

- the environment, unless the target names its own inside the recipe
- one row per parameter, each saying what the value is for and whether it is required
- a **Dry run** switch where the target supports one, which adds `--check`
- a parameter declared `secret:` typed without being shown, kept out of the preview, the history and the parameters that are stored
- `Ctrl+Return` to launch without reaching for the mouse. Plain `Return` does nothing, because a stray keystroke in a form that runs deployments should not launch one
- the exact command, updating as you type, so nothing is launched that you have not read
- for the most dangerous targets, a box asking you to type the environment name

Search classifies matches instead of scoring them. Typing `patch` finds `patch-status`, then `patch-fleet`, then anything that merely contains those letters, and each row says which kind of match it was. Scattered letters in the wrong word never outrank the word itself.

## Asking hosts a question

Manage environments… has a button beside each usable environment asking whether you can reach those hosts. It runs `ansible <group> -i <inventory> -m ping` and changes nothing.

Only three modules can be asked, and none of them changes a host: `ping`, `setup` and `gather_facts`. `command` and `shell` are deliberately missing, because they are how anything at all gets run and the catalogue is this console's safety boundary. Anything that changes a host stays behind a declared target, where the danger label, the confirmation and the lock all apply.

A probe is recorded like any other run and labelled as neither a deploy nor a cutover, so it can never move a delivery measure.

## A runbook is more than a command

A target tells you what command runs. A runbook tells you who owns it, what has to be true beforehand, what proves it worked, and what to reach for when it did not. All of that is declared in `.ordane.yml` beside the danger label:

```yaml
targets:
  deploy:
    danger: high
    owner: platform
    reviewed: 2026-08-01
    docs: docs/runbooks/deploy.md
    precheck: check
    postcheck: verify-deploy
    recovery: maintenance-off
    policy:
      max_hosts: 20
      refs: [main, "release/*"]
      clean_tree: true
```

The checks run around the operation as a single sequence. The precheck goes first, and if it fails the deploy does not happen. The postcheck goes afterwards and tells you whether the change is verified. A failed operation does not run its postcheck: a postcheck exists to prove a change worked, and asking it about one that never happened just reports the same failure twice. You get offered the recovery instead.

Only the operation counts as a deploy. The checks are recorded under their own kinds and carry no labels, so a precheck can never move a delivery measure.

The policy block can refuse a launch, and it gives you every reason at once. Fixing one thing only to be refused again is how people stop reading the reason.

A runbook nobody has reviewed in a year is marked `STALE`, on its row and in the form. Never having been reviewed is not the same as stale: somebody looking and then stopping is a different gap from nobody looking at all.

None of this is inferred. A precheck nobody named does not run, and a recovery nobody wrote is not offered. An undo you assume exists is more dangerous than one that is plainly missing, because people plan around it.

## What a playbook is made of

Ansible already composes, through roles and `import_*` and `include_*`, and your Makefile orchestrates on top of that. Nothing here builds a second composition system. The form just reads the one already in the file:

```yaml
targets:
  deploy:
    playbook: actions/deployment.yml
```

You name it rather than the console guessing. A `make` recipe can call anything, and a wrong guess would produce a listing about the wrong file. A target that was discovered as a playbook needs no key.

Made of N parts lists each role and task file, and says whether it is chosen before the run or while the run goes. An `import_` is resolved before anything starts; an `include_` is resolved while it is running.

> [!WARNING]
> A playbook that chooses part of itself at run time makes the predicted reach less reliable, and the form says so underneath: *1 of these are chosen while the run goes, tasks/preflight.yml. What they do is not known until then.*
>
> It reads what the file names, and no more. It does not resolve a variable, evaluate a `when:`, or follow an import into the file it points at. A listing that pretended to do any of those would be a worse guess than an honest one, so a name that is itself a variable is flagged instead of resolved.

A target other runbooks lean on says so too: *2 runbooks lean on this one: deploy, checks with this first · deploy, proves itself with this*. That is worth knowing before you change it, since a target three runbooks depend on is a different proposition from one nobody calls.

## What an environment is made of

Under the environment chooser, the form tells you what that environment actually holds: how many hosts, which one builds, and the other groups by name.

```text
7 hosts · builds on example-stage-builder · admin, apps, cron, varnish, web
```

The builder gets called out on its own because it is not like the other groups. A deploy of this shape builds the release on one host, ships the artifact to the web fleet and activates it there, which is what makes the cutover quick and also makes that one host a dependency of every release. It can be the same host for more than one environment, which is worth knowing before you deploy.

A run records the builder it went out through, taken from this same answer at launch, so `Built on` stays on the run permanently and a graph store can be asked what has shipped through a given host. The answer comes from `ansible-inventory --list`, asked on a thread once per environment and remembered for as long as the form is open. If Ansible is missing, or cannot read that inventory, the line says so and nothing else changes. It is something the console could not look at, not a reason the run cannot go.

An environment named by `make help` has its inventory found on disk, at `inventory/<name>`, `inventories/<name>` or `environments/<name>`, as either a file or a directory. Without one, the name is all the console has and there is nothing to look inside.

## What a run told the outside world

A deploy of this shape opens a PagerDuty maintenance window, marks the release in New Relic, posts a Noibu webhook and says something in Slack. Every one of those is `failed_when: false`, because instrumentation should never be the reason a release is lost. The side effect is that a webhook which never landed costs the deploy nothing and stays invisible unless something goes looking.

The playbook already says which of them landed. Name that task and the run reads it back:

```yaml
notifications:
  task: Report which notifications landed
```

The run then carries a **Told the outside world** panel reading *2 of 3 landed*, with a row for each and a `DID NOT LAND` badge on the one that failed.

> [!NOTE]
> **`0 of 3 apps FAILED` is a success**, and it contains the word FAILED. A row is read as landed when it says `ok`, or when it counts zero of something as failed; anything else that mentions failing is a miss, and anything else again is shown without a verdict rather than guessed at.

## Watching a run

A live run shows which task it is on, and how many have gone, under its header. When it ends the recap tells you more than that line could, so the line disappears.

`Ctrl+F` searches the output. Every match is highlighted, the current one more strongly, and the count reads `3 of 17`. `Enter` and `Shift+Enter` step through them.

A run that asks for a vault password can be answered here. A field appears above the output naming what was asked, and what you type goes to the process through the pty it is already talking on and nowhere else: not the history, not the output, not this machine. The redactor learns it too, so it stays masked even if Ansible echoes it back.

## Runs

The list on the left, one run open on the right. Every run this console has launched, **grouped by the day it happened on** and scoped to the repository you are driving. **One history file serves every control plane and every view scopes to its own**, so one estate never judges another's runs.

### A row has to earn its line

A repository that pings every half hour produces about fifty runs a day, forty-eight of which say the same thing. Listed one per line, that history stops being information and becomes a log — and a log is what this exists to be better than.

So consecutive runs fold into one summary row when **all** of these hold: same action, same environment, it passed, nothing changed on any host, and nobody pressed a button for it — a scheduled run, a repeat, or a check inside a runbook. **If you pressed the button you get your own line**: you were there, and you will look for it.

The folded row still prints its count — *44 passed · Routine runs — ping, check* — and opens in place. Nothing is hidden, only folded.

### A row prints only what deviates

Zero is not news. An unchanged host count is left out rather than rendered as `0`, and a duration is printed only for a live run or one that took unusually long for its action.

What a row carries is four things: the outcome, the action on its environment, the one fact that explains the outcome, and when. The fact is a sentence fragment — *4 of 6 hosts changed*, *db-01: lock timeout after 2m 41s* — not a number in a column.

### Shape before text

Overview puts a 24-hour ribbon above the rows: one tick per run, short and pale for a routine pass, full height and coloured for anything that changed, drifted or failed. Forty-seven runs occupy one band and answer *was today normal?* before a word is read.

Overview shows at most five rows that deviated plus one folded row. If more deviated, the last row says how many and links here.

### The two filters

**Worth a look** is the default and it is the folding above: it never hides a failure, a change, or a run somebody launched by hand. **Everything** prints one line per run. Beside them, the same four questions this history has always been asked: everything, what broke, what is still going, and what touched customers.

Under the list is **Decisions** — what was *changed* here, as against what was *run*. A ref switch, an environment being allowed, an objective being set. A run is not the only thing that decides what this console will deploy.

## Environments

One row per environment the repository declares: where its hosts come from, whether the last run matched, and a pill in one of four words.

An environment that is waiting on you is opened out, with the sentence saying what it needs and the button that gives it. **Waiting is blue, never amber.** Not having finished setting something up is not a fault, and spending the alarm colour on it leaves nothing to escalate to when something actually breaks.

**Ask its hosts** runs a ping against an environment. It changes nothing, and it is recorded as neither a deploy nor a cutover, so a probe can never move a delivery measure.

## Delivery

All four delivery signals, each either a figure with the range it was computed over, or a dormant card saying in a sentence what would turn it on. A chart's axis labels name the same range as the line above them.

Below them the service objectives, each with a gauge that carries its own target tick, so you are not asked to hold two numbers and compare them yourself. An objective with no source says what it is short of — *Needs 1 cutover*, *Needs a probe* — rather than the words `Setup needed`.

At the foot is what these numbers do not cover, in the copy rather than in fine print. A restore is the deploy that followed a failed one; nothing here reads an incident tracker.

## Setup

Seven steps, in the order that makes each one possible, reached from the card on Overview. Each one turns a specific thing on and says which, so you can stop after any of them and the console still works. It stops existing at seven of seven.

## The command palette

`Ctrl+K`. Type, arrow, enter. Four groups: **Run** an action against an environment, everything you can do to **this repository**, **switch** to another one, and **go to** a place.

Every one of the nine repository actions that used to be a row in the rail is here, and none of them is in the rail. The rail is for places.

## Watching a run

A run opens with its result first and its output below.

Ansible's own output is parsed into a conclusion: per-host `ok`, `changed`, `failed` and `unreachable` from the recap, plus each failure with the task that produced it. Output with no `PLAY RECAP` says it has none, because showing zeros would read as a clean run.

A finished run can be run again, using the same command taken from what the run recorded. Where the recap named hosts that failed, a second button runs it against only those. Two cases are refused rather than guessed at: a run whose command carried a secret cannot be replayed, because what was written down is not what ran, and a run driven by `make` is not handed a host limit its wrapper might ignore.

A live run shows how long it has been going, because a run with no elapsed time is indistinguishable from one that has hung.

The output streams while the run is alive and keeps its colour. **Scrolling up stops it following**; scrolling back to the bottom resumes. **Cancel** signals the process; the run is recorded as cancelled rather than disappearing.

An empty pane tells you which kind of silence it is: a run still starting, or one that printed nothing at all.

Every run is written to `~/.local/state/ordane/runs.jsonl`, with the output beside it. **The output is redacted before it is stored**, using a pattern set built for the job. That is a second line of defence; the first is `no_log: true` on the tasks that handle secrets, and it belongs in the playbooks.

## Keyboard shortcuts

| Key | What it does |
|---|---|
| `Ctrl+1` | Go to Overview |
| `Ctrl+2` | Go to Actions |
| `Ctrl+3` | Go to Runs |
| `Ctrl+4` | Go to Environments |
| `Ctrl+5` | Go to the Estate |
| `Ctrl+6` | Go to Delivery |
| `Alt+Left` | Back to the place before this one |
| `Alt+Right` | Forward again |
| `Ctrl+K` | Search or run a command |
| `Ctrl+F` | Find an action |
| `Escape` | Clear the search |
| `Ctrl+O` | Open another control plane |
| `Ctrl+R` | Re-read the repository |
| `Ctrl+,` | Open the configuration file |
| `Ctrl+B` | Show or hide the rail |
| `Ctrl+?` | Show these shortcuts |
| `F1` | Open the user guide |
| `Ctrl+W` | Close the window |

This table is checked against the application. The window binds its keys from one list, the menu draws its accelerators from that same list, and the shortcuts sheet is generated from it. A test fails if this page names a key the list does not carry, because a documented shortcut that does something else is the kind of error nothing else catches.

## Checks a control plane runs against itself

```bash
ordane checks --repo ~/control-plane
```

You declare them in `.ordane.yml`, and they run in a container the repository names:

```yaml
validation:
  image: ghcr.io/ansible/community-ansible-dev-tools:v25.1.0
  checks:
    - name: Syntax
      run: [ansible-playbook, --syntax-check, playbooks/deployment-playbook/playbook.yml]
    - name: Lint
      run: [ansible-lint]
```

This is not an execution node. The running stays on this machine, as you. What the container pins is the environment: which Ansible, which collections, which Python. Otherwise a run uses whatever `ansible` happens to be on the PATH, which is the one thing a reproducible release cannot depend on.

What you get is validation without a host in the room: the things a pipeline would run on a push, run here before a deploy instead.

> [!NOTE]
> Read-only, no network, and as you rather than root. The repository is mounted `:ro`, the container gets `--network none`, and it runs as your uid. A check that needs to write to the repository or reach a host is not a check, it is a deploy, and deploys go through a target where the danger label, the confirmation and the lock all apply.
>
> Nothing here mounts a docker socket or passes `--privileged`, and there is a test asserting both.

In the window this is **Run this control plane's own checks…**, in the menu and the rail. You get one row per check, its state as it lands, and its output folded away. Only a failing check opens itself, since a passing one's output is evidence you might want later rather than something to read now.

A runbook can turn them into a gate. `validate: true` on a target runs the suite before anything else, and a check that fails stops the deploy:

```yaml
targets:
  deploy:
    validate: true
    precheck: check
    postcheck: verify-deploy
```

A suite that cannot run does not pass the gate. No docker, no image or no checks stops the launch and says so, because a gate somebody declared should never be satisfied by its own absence.

A launch is one thing in the history. A runbook writes four records, for its checks, its precheck, the operation and its postcheck, and each one carries the launch it belonged to. Open any of them and **Part of one launch** lists the others in the order they ran, with the one you are looking at marked. Without that, the only thing relating them is the clock.

A suite is recorded in the run history under its own kind, carrying no labels, with every check's output kept as its transcript. Evidence nobody wrote down is only a claim, and *the checks passed before this went out* needs to be something you can point at an hour later. Each failing check is listed by name instead of being left in the output, and no recap is claimed, because no play ran and host counts on something with no hosts would be an invented measurement.

Docker is optional. Without it, `checks` says so and nothing else in the console changes. A control plane that declares no suite simply has none.

## A control plane that lives on GitHub

Cloning it and pointing the console at it has always worked. What is newer is that the console can do the cloning and change the ref for you.

```bash
ordane clone https://github.com/you/control-plane.git --into ~/src
```

Or use **Open from a git URL…** in the menu. It clones with the credentials git already has, from your ssh agent or credential helper. This console never asks for a password and never stores one, and if the clone needs authentication it does not have, you get git's own message.

Only https, ssh, git and file URLs, or an absolute path, are accepted. Other transports are refused rather than tried, because `git clone ext::<command>` runs a command the URL chooses.

### Choosing which ref runs

Choose what runs… lists every branch and tag, local and remote, newest first, with the commit and its subject. **Fetch** asks the remote and changes nothing that is checked out. On the command line:

```bash
ordane refs --repo ~/control-plane --fetch
```

```bash
ordane use origin/release --repo ~/control-plane
```

> [!WARNING]
> A ref brings its own Makefile, playbooks, inventory and `.ordane.yml`, including which environments may be launched against. A branch can allow one the branch you were on did not. That is what `git checkout` has always meant, which is why this console says it out loud: switching prints what the new ref allows that the old one did not, and the desktop raises it as a notice you have to dismiss.

There are two things it will not do. It will not switch over uncommitted changes, so commit or stash them first; that decision is yours rather than the console's. And it will not switch while anything is running out of that checkout, including a run started by somebody else's console, because the lock is a file on disk rather than a fact about this process.

A run records the ref it went out on: the branch, the commit, and whether the tree was dirty. So the history tells you what was deployed rather than what happens to be checked out now. It records the builder too, so you can see which host made the artefact and not only which environment received it.

## More than one control plane

`Ctrl+O`, or the menu, opens another one in a second window. Switching the repository under a live run would take that run's window away from it. The ones you have driven before are listed in the same place, and any that have moved are dropped from the list rather than offered.

`ordane` with no argument reopens the last one, which is what the launcher entry runs.

## When nothing can be launched

A fresh control plane is read-only on purpose. Until an environment is named, every target is listed and none can run. The alternative is a console that deploys to production the first time somebody clicks the wrong row.

The Actions view says so and offers the way out. **Manage environments…** lists what was found, says which cannot be used and why, and writes the one line that decides it.

An environment nothing found can be added by name. Its inventory might live somewhere this console does not look, or might not be a directory at all. Adding it here writes it under `environments.names`, which is read back alongside whatever discovery found.

It edits nothing else in the file. That list sits among the comments explaining why it was empty, and re-serialising the document with a YAML writer would answer the question by deleting the explanation. Only the line is replaced, and the rest of the file is left byte for byte. If the result would not parse, or would not hold what you chose, the write is refused instead of applied.

## Service objectives

**Set up…** beside that heading opens the editor. An objective is a target this estate holds itself to, and each one says what it is measured from:

| Measured from | What it needs |
|---|---|
| Cutovers that finished without a rollback | Runs recorded here, against the environments you scope it to, on targets marked `cutover: true` |
| Cutovers that finished inside a time limit | The same runs, and a limit in seconds |
| Something this console cannot measure | A sentence saying what it would take, rather than a number |

The third is not a failure state. An objective with no source is a real thing to declare: availability needs a probe that should not run on a laptop, and saying so is more useful than a number nothing computed.

Saving rewrites the `slos:` block in `.ordane.yml` and touches nothing else in the file.

## The rail, the menu, or both

The rail holds the places and the menu holds the application: preferences, shortcuts, the guide, and what this is. A window opens with both, and **Preferences** is where you say otherwise. A narrow window folds the rail away and keeps the menu whatever you chose, because places with nowhere to be reached is not a preference.

## Two people, one environment

A run takes a lock, and that lock is a file every console can see. Launching something already running against the same environment is refused, and you are told who holds it and since when. Two people running different runbooks against one environment is allowed; set `lock: environment` in the configuration if you would rather it were not.

A lock whose process has gone is cleared automatically. A lock held by another machine is not, because this console cannot ask that machine whether it is still going, and clearing a lock that was not actually stale gives you a second deploy.

## The dataset

The history is one record projected three ways, so a shared store can read it without this console keeping a second copy of anything:

| Projection | What it is |
|---|---|
| **Facts** | One flat row per finished run: who, where, what, how long, how many hosts, how many changed |
| **Series** | Six measurements per run, tagged with the control plane, environment, target, actor, host and outcome |
| **Graph** | Control planes, environments, targets, actors, hosts and runs, and **which hosts a run actually touched**, which is the one relationship a row cannot carry, because it comes out of the recap rather than out of what was launched |

*Export the history…*, or in a terminal:

```bash
ordane export --repo PATH --format csv -o runs.csv
```

Four shapes: `jsonl`, `csv`, **InfluxDB line protocol** and **Neo4j `MERGE` statements**. `--everything` widens it from this control plane to every one in the history.

Nothing connects to anything. A projection is data, and where it goes is your decision, which is what lets the console work without any server running. The Cypher is `MERGE` rather than `CREATE`, so loading the same export twice is a no-op.

A run missing something appears as `(unattributed)` rather than vanishing. A record with no control plane once produced edges pointing at a node nothing had created, and the store silently dropped 14 of 54 of them on load. A gap has to be visible to count as a gap.

### An environment whose hosts EC2 decides

Manage environments… → From EC2 writes the configuration file Ansible's own `amazon.aws.aws_ec2` plugin reads, into `inventory/<name>/aws_ec2.yml`, and adds the environment to the allow list.

You give it regions, the tag whose value should become the group name, and optionally a tag to filter on and a named AWS profile. It previews the whole file before writing anything.

> [!IMPORTANT]
> This console never talks to AWS and never writes a credential into that file. Ansible's plugin does the asking, using boto3's usual chain of environment variables, a named profile, an instance role or SSO. The plugin will accept a key and a secret inline, and this refuses to write either, because a repository is the worst place to keep them.

It writes a directory rather than a bare file, because Ansible detects the plugin by filename. `-i inventory/production` reads the whole directory, which keeps your environment called `production` instead of `production.aws_ec2.yml`.

You need the `amazon.aws` collection and `boto3` installed. Without them, or without credentials, the environment comes back unreadable and the console prints Ansible's own reason:

```text
Ansible could not read that inventory.
Insufficient boto credentials found. Please provide them in your inventory
configuration file or set them as environment variables.
```

> [!WARNING]
> An inventory plugin that fails does not fail the command. `ansible-inventory` prints a warning, returns a valid empty inventory and exits `0`, so a fleet nobody could reach and a fleet with nothing in it look identical by exit code and by output. The console reads the warning, which is how those two now say different things.

## The Estate

This has a view of its own on purpose. Everything else in the console reads files on this machine and works with nothing running, while this one asks a shared store, so it is the only page that can be sitting waiting on a network.

The tab is always there, and it will fill the settings in for you. Open it before anything is configured and it offers **Point at the stores…**, a form for both stores that is also on the rail and in the menu. What you type is written to a file only your account can read:

```text
~/.config/ordane/stores.env
```

It is written `0600`, and an existing file is tightened to match. That matters more than it sounds, because a file written by hand takes whatever your `umask` gives it, commonly `0664`, which every account on the machine can read, token and all.

An environment variable of the same name wins, so a shell pointed somewhere else for one session does not have to edit anything. Here are the same keys, if you would rather write the file yourself:

```bash
ORDANE_INFLUX_URL=http://localhost:8086
ORDANE_INFLUX_TOKEN=
ORDANE_INFLUX_ORG=ordane
ORDANE_INFLUX_BUCKET=control-plane
ORDANE_NEO4J_URL=http://localhost:7474
ORDANE_NEO4J_USER=neo4j
ORDANE_NEO4J_PASSWORD=
```

The same names in the environment win over the file, so a shell that already exports them keeps working and a CI job needs no file at all.

The console writes this one file and nothing else that holds a credential. It used to refuse even that, until it became clear the file exists either way and a hand-written one is usually left world-readable. See [SECURITY.md](../SECURITY.md) for the reasoning and for everything the console still will not write.

The clients are read-only, so nothing in this console can change what is in a store.

The page re-reads the file every time you visit it, so writing it does not mean restarting the console. Switch away and back.

It opens with four figures, each of them arithmetic on what a store answered: how many releases this year and what pace that is, how many are on record and how far back they go, the busiest full year, and the median lead time against last full year's. A store that did not answer contributes no figure at all, rather than a zero.

Both yearly charts carry their own axis, with the value printed on each bar and each point, so nothing needs tabling a second time underneath. The running year is drawn open, as an outlined bar with a hollow marker, because a short final bar in a year that has not finished reads as a fall when it is nothing of the sort.

Asking again keeps what is already on screen. The figures stay put and the header says how old they are while the next answer is in flight. Only a first ask gets a blank page.

Five panels, and **each is here because the local history cannot answer it**:

| Panel | Why it needs a store |
|---|---|
| Releases a year | The run history starts when this console did. The release log goes back to 2020 |
| Lead time, a year at a time | The same |
| What went out through each builder | One builder can package releases for several environments, and for control planes this machine has never driven |
| What shipped between platform upgrades | A path through the release chain, and no table has a path in it |
| What is patched, and how much anybody watched | A ledger seeded from disk is a claim about the past, not a record of one |
| Hosts that failed under a run | Which hosts a run reached comes out of the recap |

Panels are laid two to a row, and a table prints four rows before telling you how many it is holding back. The page is meant to be a shape you can read, not a dump of the store.

A panel that could be answered from the local history does not belong here, since it would be a slower copy of Health with a network dependency attached. A store that cannot be reached says so panel by panel, and every other view carries on regardless.

## What gets backfilled

`ordane export` includes two records this console never wrote, when the control plane has them:

- `docs/dora/backfill.jsonl`: the reporter's release log, with the chain between releases. `docs/dora/history.csv` is the fallback, and the export says when it fell back
- `patches/ledger.jsonl`: what is applied where, and whether anybody watched it happen

Neither is written to. `--runs-only` leaves both out.

## Running as root

Don't. Nothing here needs it, because Ansible escalates on the hosts it reaches rather than on the machine it runs from. A console started as root gets a banner that will not go away, a block of text on stderr before anything runs, and a failing `doctor`. It is not prevented, since `sudo` is yours to use, but nobody is going to do it without noticing.

## When something is wrong

Menu → Check this control plane looks at everything that can be checked without launching anything, and tells you what to do about whatever it finds:

- a name in the allow list that `make help` never prints, since a misspelling here raises nothing and silently leaves the console read-only
- a target the config still groups that the Makefile no longer has
- a `choices_from:` that matches nothing, which leaves a required field with nothing to fill it
- a shortcut target naming an environment that does not exist, so the allow list would be checked against a name the run never reaches
- whether the release history and the event log are readable, and whether GTK is available

The same thing runs in a terminal:

```bash
ordane doctor --repo ~/control-plane
```

It exits non-zero only when something is genuinely in the way, so it can be used in a check.
