# Changelog

Notable changes, newest first. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the versions follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
