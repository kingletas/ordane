# Contributing

## The gate

```bash
make check
```

Ruff and the unit suite. A commit has to pass it, and CI runs the same thing on every push and pull request.

```bash
make smoke
```

This drives the real window against the example control plane and writes a PNG of each view into `docs/images/`. Run it for anything that touches the interface, and then actually look at the pictures.

> [!NOTE]
> `make smoke` is not part of `make check`, and it is not a CI gate either. It opens a real window and drives it, so its checks are timing against a live GUI on a machine whose speed and font this repository does not control. CI runs it on every push and uploads the screenshots, but a red cross there means look at the pictures, not stop.
>
> That does not make it optional. Almost every interface defect in this project was found by opening the window and looking, and several times the unit suite happily exercised a component while the route through it was broken.

## Where a change goes

Words a person reads do not belong in a front end. A danger level, a run state, the name of a measure: put those in `src/ordane/language.py` once, and all three front ends read them from there. A string typed straight into a template is a string the other two will eventually contradict.

Decisions do not belong in a front end either. If the desktop app and the terminal would both have to answer the same question, the answer goes above the line. See [docs/architecture.md](docs/architecture.md).

## Documentation is part of the change

- A new keyboard shortcut goes in `desktop/shortcuts.py`, and nowhere else. The window, the menu and the shortcuts sheet all read that table, and a test fails if `docs/user-guide.md` names a key it does not carry.
- A new configuration key goes in `docs/configuration.md`, in `examples/ordane.full.yml`, and in `examples/control-plane/.ordane.yml` where it can be seen working. A test fails if the full example is missing a key the loader reads.
- A new command goes in the CLI epilog, which is what `--help` prints.

## Comments

Say what the code does or what it guards against, in a sentence or two, then stop. History belongs in the commit message and the changelog. A comment has no diff and no timestamp, so it is the one place nothing will ever check.

## Tests

Test both directions, every time. A passing check tells you nothing about the case it is meant to catch until you have watched it fail. The smoke's read-only path exists for exactly that reason: the loud path passing said nothing about the quiet one.
