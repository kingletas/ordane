# Changelog

Notable changes, newest first. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the versions follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.0]: 2026-09-08

The whole interface has been rebuilt to a design direction called *Bridge* — a ship's bridge, where the state is visible at a glance and the controls are within reach of the person reading the instruments. Everything in it follows from one job: know whether it is safe to act, act, then see what happened.

Nothing was taken away. Every dialog, every keyboard shortcut, every policy and every record the previous version had is still here, and the engine underneath is unchanged.

### Changed

The rail holds places and nothing else. It used to carry fourteen rows, nine of them ending in an ellipsis because they opened a dialog, while the real navigation sat in the title bar — two navigation systems, neither of them complete. Those nine were never navigation: they are methods on the repository. They have moved to a menu on the repository card at the foot of the rail, and to a new command palette. There are six places now — Overview, Actions, Runs, Environments, Estate and Delivery — and three screens reached from them: Setup, About and Preferences.

Configuration you have not finished is blue, and amber and red are kept for things that actually went wrong. That one change is what stops a first launch looking like an outage. Five scattered `Setup needed` cards and a *Needs attention* banner are now one blue setup card and one ordered list of seven steps, each of which says what it turns on.

Overview leads with a single sentence saying whether it is safe to deploy, and one line naming the thing standing in the way. Under it are the environments as tiles, the delivery measures, the objectives with a target tick on each gauge, and what ran today.

A history of fifty runs a day is readable again. Consecutive routine passes that changed nothing fold into one row that still prints its count, and anything that failed, changed something or was launched by hand always keeps its own line. Rows print no zeroes: an unchanged host count and an unremarkable duration are left out rather than rendered as `0`. Above them a 24-hour ribbon answers *was today normal?* before a word is read.

A run shows its own shape: one lane per host, one cell per task, read back out of the same output the log shows. That is the one thing a log cannot do, and it fills in while the run is still going.

Two commands that were the same thing under different names are one. *Check this control plane* and *Check the setup* have become *Check that this repository is set up correctly*.

Manrope and IBM Plex Mono are bundled under the SIL Open Font License. Mono is used only for a string somebody could paste into a terminal, and no label anywhere is set in capitals.

Preferences is a place rather than a dialog, and every row in it is wired to something: theme, density, reduced motion, re-reading on focus, reopening the last repository, and where the rail and the menu live. What is not built — confirming before a change, stopping at the first failed host, pruning old history — is named at the foot rather than shown as a switch that would do nothing.

### Added

- A command palette on `Ctrl+K`, grouped as Run, This repository, Switch and Go to. Every action can be launched from it, and all ten repository commands are reachable there.
- Environments and Delivery are places of their own. The environment that is waiting on you says what it needs and carries the button that gives it.
- A dark scheme, and a theme choice that stops following the system when you say otherwise. Every text colour in both schemes is measured against WCAG 4.5:1 by a test.
- `ordane --page` accepts `overview`, `environments`, `estate` and `delivery` as well as `actions` and `runs`.
- The demo history now seeds two days of half-hourly scheduled pings, so the run-density rules have something to fold.

### Fixed

- The Actions list repeated the same environment chips on every row. Where every action reaches every environment the column carries nothing, and on a control plane with thirty-seven actions and four environments it took a third of the row from the descriptions, which then ellipsised after four words. The chips are drawn only where an action reaches somewhere different from the rest, and the fact is stated once above the list instead.
- One long label could decide how wide a whole screen had to be. A `Gtk.Label` that neither wraps nor ellipsises reports its entire text as its minimum width, that became the minimum of the row, the card and then the page, and the page asked for more room than the window had — which GTK answers by drawing widgets on top of each other. A band's context line ellipsises now, and `tests/test_widget_widths.py` measures each piece with text long enough to break it.
- The lane chart of a live run was appended once a second instead of being updated, so a run watched for twenty seconds carried twenty stacked copies of its own hosts. The card grew with them until the output pane was drawn on top of the recap above it. The chart is now rebuilt only when the shape of the run changes — a new host or a new task — and the cells are updated in place.
- Everything above a run's output is bounded and scrolls on its own. A box whose children ask for more height than it has does not push them off the bottom, it draws them on top of each other, so the run detail could overlap itself on a short window whatever else was going on.
- A run that was still going could keep saying `Running` after it had ended. The pane beside the run list was handed the record of the newest run rather than the run itself, so it had no stream to follow and no way to learn that the run had finished, while the list beside it had already moved on.
- The two split screens stayed side by side in a window too narrow to hold them. `Adw.Breakpoint.add_setter` applied nothing for the orientation property and said nothing about it; the orientation is set from the breakpoint's own signals now.
- A delivery chart's axis disagreed with the figure above it. Release frequency drew a fixed eighteen-month window while the basis line named the actual first and last release; both now describe the same range.
- White on the action colour is unreadable in a dark scheme, at 2.2:1. A filled button's text colour is part of the palette now rather than assumed to be white.
- `make smoke` photographed nothing on a Wayland desktop, and said so as thirty skipped screenshots rather than as a failure. `xvfb-run` sets `DISPLAY`, and GTK prefers Wayland whenever `WAYLAND_DISPLAY` is also set — so the window opened on the real compositor, was mapped and correct, and was never given a frame. The backend is named when both are set, and a run that misses more than two frames now fails instead of skipping. A check that cannot fail is not a check.
- A run of a single task drew a chart that said nothing. One column is a full-width bar per host carrying one outcome each, which the pill above it already states; `ansible -m ping` against a host group produces exactly that. A run needs two tasks before its shape is worth drawing, and below that the recap opens unfolded instead.
- Host names moved the bars beside them. The name column had a pixel floor, and a floor is only a floor — a longer name simply took more than it, so every lane started somewhere different and the chart read as ragged rather than as a grid. The column is measured in characters from the names actually in it, capped, with the full name as a tooltip.
- A run's output pane could be squeezed to nothing by the detail above it. The card and the log are two halves of a drag handle now: the boundary is placed to fit the detail, never takes more than two thirds of the pane, always leaves the log a floor, and stays wherever it is dragged.
- Action descriptions ellipsised after four words while the name column beside them held whitespace. That column is measured from the names in it too, within bounds, which is the same fix as the lane chart's.
- The run form offered a command it would have refused. A target with a required parameter still empty had its preview built without being validated, so `WILL RUN` printed `make patch-fleet environment=docker` — a line missing the two values the target insists on — and the Run button sat there ready. The preview is validated before it is built now, Run is held while there is nothing to run, and its tooltip names the field that is missing.
- Parameters are read out of the Makefile, so a target that takes inputs offers a form without anything being declared first. A control plane already says what its recipes need — the `# make <target> key=value` line above a recipe names the fields, a `test -n "${key}"` guard inside it (or inside the script the recipe calls) makes one required, and a help line reading `(requires x=)` names one that has no example. Only a name that is documented that way becomes a field: a recipe reads plenty the deployment supplies, and offering `inventory` or `owner` would ask somebody to fill in what is already known. Anything declared in `.ordane.yml` still wins, which is how a free-text field becomes a choice list.
- The composer offered to run an action it could not run. A target with a required parameter still empty had a button reading `Run apply-patch on production` and a line saying it makes no changes; pressing it could only refuse. It reads `Fill in apply-patch…` now, opens the form, and the line above it names what is missing.
- A choice list is typed into rather than scrolled. Sixty-three patches in a dropdown is a list somebody hunts through; typing three characters and picking from what is left is the same choice made in a second. What starts with the typing comes first, what merely contains it follows, and case is ignored both ways. Arrow keys and Enter work, Escape closes it, and a short fixed list like `present` or `absent` stays a dropdown because it is quicker to see than to type.
- A patch that is not on disk yet can be pasted in. The suggestion list ends in `Paste a new patch…`, pinned below the scrolling part so it is reachable however long the list is, and it writes one file into the folder the list is read from. It refuses rather than corrects: a name that is not a name, a name that would write outside that folder, a name already on disk, an empty paste, and a body carrying none of `diff`, `---`, `@@` or `Index:`. The file lands readable and not executable, and the field is filled with what it wrote.
- Anything that can be added to is now a typing field however short its list, because a dropdown has nowhere to offer the entry that is not there yet.
- Where a run is aimed decides how it is presented, not what the action is called. `ping` against docker is a keystroke; the same `ping` against production is a keystroke against the thing customers are using, and no Makefile has ever said so. The environment's own name is the evidence: `production`, `prod`, `prd` and `live` are production, and `staging`, `stage`, `dev`, `docker` and `local` are the safe kinds. Everything else is unknown rather than safe, and says so — `Could be dangerous: nothing in the name says whether that is production`. A production run is red whatever it does, an unknown one is amber, and an action's own `danger` rating can raise that but never lower it.
- `ordane doctor` reports what it can tell about each environment, and names the ones whose names say nothing. Every warning in the interface rests on that reading, so an unreadable name is the one place the gap has to be reported on its own.
- Environments carry a chip saying how exposed they are, in the Environments place and on the Overview tiles, so it is visible before anybody chooses one.
- `make smoke` no longer rewrites thirty-two committed PNGs on every run. The frames go to `local.d/shots`, which is ignored; the two the README shows are copied across by hand and are the only ones the repository keeps.

## [0.1.1]: 2026-09-06

### Fixed

The window smoke test failed at random on a loaded machine. Checks read the interface a fixed pause after asking it to change, and screenshots polled for a frame instead of asking for one. Each check now waits for the condition it is about, and a frame that never arrives is reported as a screenshot not saved rather than as a failing check.

Nothing in the application changed. This only affects `make smoke`, which is a development tool.

## [0.1.0]: 2026-09-06

First public release. Ordane grew out of driving a real control plane and wanting a record of it; this is where that got to before it was worth showing anyone.

Treat it as a prototype with a decent body of code behind it. It works, it is tested, and the interfaces will still move.

### What it does

It reads your control plane as it already is. If there is a Makefile, it takes the targets from `make help` and runs them for you. If there is not, your playbooks are the catalogue and it calls `ansible-playbook` itself. Neither shape has to change to be driven from here.

Before a run it shows you the exact command, what the environment holds, and what the playbook is made of. Afterwards it keeps the record: the command, what Ansible reported, how long it took, the branch and commit it went out on, and which host built the release. The delivery measures and service objectives on the Health view are computed from that, and anything it cannot source says so rather than showing a zero.

Nothing is launchable until you have named the environments it may reach. A target can carry a runbook: an owner, a precheck, a postcheck, a recovery, and refusals like a host ceiling or a clean working tree, and a control plane can declare its own checks to run in a container as a gate on a deploy. An environment can be built from EC2, in which case what gets written is the config Ansible's own inventory plugin reads.

The same engine drives a desktop window, a terminal and a browser, so the three cannot tell you different things.

It installs three ways: a wrapper in `~/bin` for working on it, a Debian package, or a flatpak. The flatpak runs `make`, `ansible` and `git` on the host through `flatpak-spawn`, since that is where your control plane and your keys are.

If you have never written a playbook, [docs/from-nothing.md](docs/from-nothing.md) goes from an empty directory to a deploy in about ten minutes.

Two example control planes come with it. One is small and reaches nothing, so every button is safe to press. The other brings up fourteen containers and genuinely deploys to them, with and without a Makefile, on the same playbooks.

### Fixed

- **A target's policy refusals now apply in the terminal as well as the window.** `policy.refs`, `policy.clean_tree` and `policy.max_hosts` were checked only by the desktop, so `ordane run` went straight past them. A refusal enforced on one front end and not another is worse than none, because it is the one people rely on.

### Known gaps

- Availability and latency need a probe, and a probe running on a laptop measures the laptop.
- Live host state is read from the event log rather than by asking the hosts.
- A run launched by hand in a terminal is not recorded. Shrinking that gap is the point of the tool, and it has not closed it.
