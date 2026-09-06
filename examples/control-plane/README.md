# An example control plane

A control plane that reaches nothing, so the console can be driven without a fleet.

```bash
make demo
```

That opens the desktop console against this folder. Everything works: the catalogue, the search, the launch form, the streamed output, the recorded history, and every target prints what a real one would do and exits.

## What each file is here to show

| File | What it demonstrates |
|---|---|
| `Makefile` | The `make help` contract, which is the entire interface between a control plane and this console |
| `.ordane.yml` | Every configuration key, annotated, including the ones that decide what may be launched |
| `docs/dora/history.csv` | The release history a reporter commits, which fills the cadence and lead-time measures |
| `patches/*.patch` | What `choices_from: patches` reads |
| `releases/*/` | What `choices_from: glob:releases/*` reads |
| `actions/*.yml` | What the `playbooks:` globs select |

## The `make help` contract

The console reads the output of `make help` and nothing else. Three things in it are load-bearing:

- A line matching `Environments…:` opens the environment block; each line beneath it is `  name`, and a name followed by two spaces and a parenthesised reason is an environment that cannot be used.
- A line reading exactly `Targets:` opens the target block; each line beneath it is `  name: description` at exactly two spaces of indent.
- A blank line closes a block.

Write a description beside a target and it appears in the console. There is nothing to register.

## Targets worth running

| Target | Why it is here |
|---|---|
| `ping` | Finishes instantly. The shortest path from clicking Run to a recorded run |
| `slow-ping` | Takes four seconds, one line a second, so the streaming output can be watched |
| `fail-on-purpose` | Exits 2 with a failed host in the recap, so the failure view has something real to show |
| `deploy` | Marked `deploy:` and `cutover:`, so running it fills the delivery measures and the objectives |
| `activate` | `danger: high` with `confirm: type-environment-name`, the full ceremony |

Running `deploy` against `staging` once is the fastest way to see a dashboard with data in it: the release-risk measure and both cutover objectives are computed from runs this console recorded.
