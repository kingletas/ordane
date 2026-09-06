# Getting started

Fifteen minutes, and the last five of them are optional.

## Contents

- [Try it without a fleet](#try-it-without-a-fleet)
- [Install](#install)
- [Point it at your own control plane](#point-it-at-your-own-control-plane)
- [Make something launchable](#make-something-launchable)
- [Everything in a terminal](#everything-in-a-terminal)
- [A browser, if you prefer one](#a-browser-if-you-prefer-one)

## Try it without a fleet

The repository ships a control plane that reaches nothing.

```bash
make demo
```

Every target in it prints what a real one would do and exits, so you can click anything. `ping` finishes at once, `slow-ping` takes four seconds so the streaming output can be watched, and `fail-on-purpose` exits non-zero with a failed host so the failure view has something real in it.

Run `deploy` against `staging` once. It is the quickest way to get a dashboard with data in it, since the release-risk measure and both cutover objectives are computed from runs this console recorded, so they fill in as you go.

The demo is documented in [`examples/control-plane/README.md`](../examples/control-plane/README.md), which doubles as the reference for adopting the console in a repository of your own.

## Install

```bash
make install
```

That puts a wrapper in `~/bin` which runs this source tree through `uv`, plus a desktop entry and icon under `~/.local/share`, so the console is in your launcher as well as on `PATH`. There is only one copy of the code: edit it here and reinstall, and never edit the installed file.

Starting it from the launcher gives you nowhere to type `--repo`, so it reopens the last repository you used. If it does not remember one, it says so and shows you the two commands worth running.

The desktop console needs GTK 4 and libadwaita from your distribution:

```bash
sudo apt install python3-gi gir1.2-gtk-4.0 gir1.2-adw-1
```

`make venv` builds the virtualenv with `--system-site-packages` so it can see them. If they are missing, the console tells you and points you at the terminal, where every view is also available. It will not die with an import error.

## Point it at your own control plane

```bash
ordane init --repo ~/your/control-plane
```

Start here. It reads the repository, writes a `.ordane.yml` describing the targets and environments it actually found, and works out which variable your Makefile reads to know where a run goes. Anything that is a judgement call, like which targets are dangerous or which count as a release, is left commented out. A starter file that guessed at those would be less useful than one that asks.

Then:

```bash
ordane doctor --repo ~/your/control-plane
```

Run this before you open the window. The doctor checks everything it can without launching anything, and tells you what to do about whatever it finds. Most of what goes wrong with a control plane is silent: a misspelt environment name never matches anything, and just leaves the console read-only without explaining why. The doctor turns those into sentences.

Then:

```bash
ordane --repo ~/control-plane
```

It needs one thing from the repository: a Makefile with a description for each target. That description can come from `make help` in either of the two common shapes, or from a `## ` comment beside the target, which is why a repository with no `help` target still works. There is nothing to register and nothing to keep in step.

> [!IMPORTANT]
> Nothing can be launched until you name an environment. A control plane the console has not been configured for is read-only, and an empty allow list is where it starts on purpose. Pointing it at your repository is safe: it will read and show you everything, and run nothing.

## Make something launchable

Every environment reaches real hosts, so nothing runs until you say which ones this console is allowed to touch.

Use **Manage environments…** in the window, from the Actions view or the main menu. Or edit the file yourself:

```yaml
environments:
  allow: [staging]
```

Everything else in [`.ordane.yml`](configuration.md) is optional. It carries the things `make help` has no way of saying: what a parameter means, which targets are dangerous, which runs count as a release. [`examples/ordane.full.yml`](../examples/ordane.full.yml) has every key in one place.

## Everything in a terminal

```bash
ordane status --repo PATH
```

The dashboard, printed. `actions`, `runs`, `show last` and `run` cover the rest, over the same engine, so a machine with no display still has a console.

```bash
ordane run deploy --repo PATH -e staging --set branch_name=main --check
```

`run` asks for confirmation on anything the config marks dangerous, exactly as the window does. `--yes` skips it for unattended use.

## A browser, if you prefer one

```bash
ordane serve --repo PATH --open
```

It binds to `127.0.0.1` only and there is no login. Anything that can reach the port can already run `make` as this user, so the port is the boundary. [SECURITY.md](../SECURITY.md) sets out what that puts the weight on.
