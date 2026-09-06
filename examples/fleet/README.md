# The fleet example

A second control plane to point Ordane at, deliberately unlike the first one. Where [`examples/control-plane`](../control-plane) is small, reaches nothing and exists so you can click every button safely, this one is bigger, has two environments of different shapes, and **its runs actually reach hosts and change them**.

It stands in for a video platform: edges, an API tier, transcoders, a queue and a database. Fourteen containers, about 7 MiB of memory between them, up in a few seconds.

## Contents

- [Start the fleet](#start-the-fleet)
- [Drive it](#drive-it)
- [The same playbooks without a Makefile](#the-same-playbooks-without-a-makefile)
- [What is worth looking at](#what-is-worth-looking-at)
- [Stop it](#stop-it)

## Start the fleet

```bash
docker compose -f examples/fleet/docker-compose.yml up -d
```

Fourteen containers running `sleep infinity`. Nothing listens on a port and nothing is published. Ansible reaches them with `community.docker`'s `docker` connection, so there is no sshd, no key to generate and nothing to trust.

You need the `community.docker` collection:

```bash
ansible-galaxy collection install community.docker
```

## Drive it

```bash
ordane --repo examples/fleet
```

`staging` is allowed and `production` is not, which is the state a real control plane should arrive in. Production is listed, described and refuses to run until you say otherwise.

From a terminal, if you would rather:

```bash
ordane run deploy --repo examples/fleet -e staging --set release_tag=2026.09.06
```

The deploy builds an artefact on one transcoder, ships it to the serving tier, then activates it one host at a time. `verify` reads back what every serving host is on and asserts they agree. It is a real Ansible run: `changed=2` means two files actually moved.

## The same playbooks without a Makefile

This is the part worth trying. Rename the Makefile:

```bash
mv examples/fleet/Makefile examples/fleet/Makefile.off
```

Nothing else changes, and Ordane keeps working:

```text
✓ 5 targets were found, across 2 environments
✓ Driven by ansible-playbook
    Targets from the playbooks on disk, named by the first play in each;
    environments from the inventory directories on disk.
```

The targets are now the playbooks, named by the first play in each, and a run becomes `ansible-playbook -i inventory/staging playbooks/deploy.yml -e release_tag=…`. The danger labels, the parameters, the runbook and the refusals all still apply, because they live in `.ordane.yml` rather than in the Makefile.

Put it back when you are done:

```bash
mv examples/fleet/Makefile.off examples/fleet/Makefile
```

## What is worth looking at

`deploy` is a runbook rather than a command. It checks first, verifies afterwards, offers `restore` as its recovery, and refuses to launch from a dirty working tree or against more than twelve hosts. Open the launch form and it tells you what it is about to touch before you press anything.

The two environments are different shapes. Staging is one of everything; production is two edges, three API hosts and two transcoders. The launch form reads that out of the inventory and says so, which is the difference between knowing what you are about to do and guessing.

`production` counts towards the delivery measures and `staging` does not. That is `metrics.environments` in `.ordane.yml`, and without it a deploy to a throwaway fleet would move a number that is supposed to mean something.

The deploy refuses a release nobody named. Try it without one:

```bash
ordane run deploy --repo examples/fleet -e staging
```

## Stop it

```bash
docker compose -f examples/fleet/docker-compose.yml down
```

Nothing survives it. The containers hold no volumes and the only state a run leaves is a file in `/tmp` inside each one.
