# Why Ordane exists

**Because deploying from a control plane repository works fine, and then has no memory of having done it.**

## The problem

The repository is in good shape. The playbooks are right, the roles are factored, the inventory is where it should be, and running `make deploy` does the correct thing. What is missing sits either side of the run:

- **Before.** The command you are about to run is assembled out of a Makefile target, a handful of variables and whatever is in your shell. Whether it is the one you meant is a thing you find out afterwards.
- **During.** Output scrolls past faster than it can be read, and the interesting line is four hundred lines above the prompt.
- **After.** The terminal closes. The only record that the deploy happened, what it changed, and whether it was clean is what somebody remembers, plus a scrollback buffer that is gone at the next reboot.

That is a real gap and it is not a tooling failure. A terminal is doing exactly what a terminal does. It just is not a record.

## Why not AWX

Because this problem is precisely AWX's problem, and the honest first answer was to install it. Two things were in the way.

**AWX stopped cutting releases on 2 July 2024**, and says so at the top of its own README.

And it is enormous. Reproducing what it does means reproducing a product built by roughly 280 contributors over nine years, standing at about 6.8 MB of Python. Adopting it means a prerequisites project of its own, because a Git-backed control plane can only drive automation that is actually in Git and in the shape it expects — which is a weeks-long content project before anything is deployed through it.

The comparison stands as the reason **not to build a platform**. Sixteen of seventeen requirement areas in the original specification mapped onto AWX features that shipped years ago. Anything that reaches for that scope is reaching for something that already exists and is not maintained.

## Why not the enterprise version of this

The requirements this started from described a multi-team platform: RBAC, approval workflows, scheduling, notifications, execution environments, reporting, SSO. All reasonable, none of them the thing that was wrong.

Ruled on 2026-09-01: neither route was taken. What is wanted is a front end for one flow — see the command, run it, watch it, keep the record — not a platform for teams that do not exist yet. Everything above was deferred rather than deleted, and the deferral is the reason this is usable now.

## What the reason decided

- **It reads the repository as it already is.** With a Makefile it drives that, taking the targets from `make help`; without one, the playbooks are the catalogue and it runs `ansible-playbook` directly. **Neither shape has to change to be driven.** A tool that requires you to restructure your automation before it can run it has moved the work rather than done it.
- **The command is shown before it runs.** That is the "before" half of the gap, and it is worth more than any feature behind it.
- **The record is the product.** Output is streamed and kept. If the terminal closing loses it, the tool has not solved the thing it exists for.
- **Three ways in, one engine.** A desktop window, a browser, and a terminal that opens nothing. All three read the same configuration, enforce the same refusals and write to the same history — because a refusal that only exists in the GUI is not a refusal.

## Where the examples came from

`examples/fleet` brings up fourteen containers and deploys to them for real. A control plane that has only ever been demonstrated against a mock has not been demonstrated.

## Where the name came from

**Ordane ordains.** It reads like *ordain*, and we let it.

To ordain is not to describe a thing. It is to make the thing so by saying it. Every office that has ever worked that way looks the same from outside: the herald who reads the decree at the gate before the gate opens, the registrar who enters a judgement into the roll, the scribe beside the throne whose absence means the order was never given at all. **Not one of them decides anything.** They stand between an intention and the world. They say it plainly first, and they write down what happened after. An order nobody spoke was never issued; an order nobody recorded was never carried out.

That is the whole of this program. It takes the command out of your shell, holds it up, and reads it back to you before a single host is touched. It watches while it runs. It keeps the record, so the deploy outlives the terminal.

Everything else here is machinery in service of those two moments — the one before, and the one after.

### The word is invented, and the meaning came second

That is the honest order of events, and it is worth stating rather than implying an etymology the word does not have. **The name had to be made up, and that was a requirement rather than a flourish.**

The working name described what the tool drives, which is a bad idea for something whose whole purpose is reaching production hosts: a name that advertises what a program can touch is an invitation to look at it. So the tool needed a name that was broad enough to cover Ansible, Terraform, Kubernetes and runbooks without naming any of them.

The first candidate was Veyra, and it failed a check rather than a taste test. Five software companies use it, one of them selling developer tooling, plus PyPI, npm and three live domains. Ordane cleared everywhere that matters — the only holders of the word are in accounting, tabletop gaming and fashion.

That check is worth repeating before adopting any name: package registries, GitHub, domains, and an open-web company search. A name that collides is a name you will be renaming later, under worse conditions.

One compatibility note follows from the rename. An existing control plane still carries the former configuration filename, so that name is still read — and `ordane doctor` names it rather than accepting it in silence.
