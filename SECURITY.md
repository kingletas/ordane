# Security

> [!IMPORTANT]
> The boundary here is the machine. There are no accounts, no roles and no server, so anyone who can run this console already has whatever the account running it has. Everything below is about what leaks out of a run, not about who is allowed to start one.

## Contents

- [The model](#the-model)
- [The one credential this console writes](#the-one-credential-this-console-writes)
- [What the console writes](#what-the-console-writes)
- [Reporting something](#reporting-something)

## The model

There is no login, deliberately. Anything that can reach this console can already run `make` as this user, so a password would only suggest a separation that does not exist.

That puts the weight on these instead:

- **The web front end binds `127.0.0.1` only.** Do not expose it on another interface. There is nothing behind it.
- **Every request is checked.** The `Host` header has to be this console's loopback address, and anything that changes state has to carry a same-origin `Origin`. Without the `Host` check, any web page you visited could reach it by DNS rebinding, and `SameSite` does not cover that on its own.
- **Parameters are allow-listed, not escaped.** Several make variables end up in a shell on a remote host. `argv` is always a list, no string is ever handed to a shell, and a value gets refused if it falls outside its declared choices or carries a shell metacharacter.
- **Nothing can be launched until it is named.** A control plane the console has not been configured for is read-only, and an empty allow list is where it starts.
- **A parameter marked `secret:` is masked everywhere it would be written down:** the command preview, the stored command, the stored argv, the stored parameters and the output. It only ever reaches the process that runs. The runner is handed the whole command instead of an argv and a string, so a caller cannot record the unmasked version by accident.
- **Output is redacted before it is stored.** Treat this as the second line of defence. The first is `no_log: true` on the tasks that handle secrets, which belongs in your playbooks: a secret that never reaches stdout does not need removing from it.

## The one credential this console writes

That file is `~/.config/ordane/stores.env`, and it is written mode `0600`.

It holds an InfluxDB token and a Neo4j password. The console used to refuse to write it at all, on the grounds that it is not a credential store. That turned out to be the wrong call: the file exists either way, and a common `umask` leaves a hand-written one at mode `0664`, which every account on the machine can read. Refusing to write it never kept the token off the disk. It only meant nobody chose the permissions.

It now goes through a single function that creates the file owner-only and tightens an existing one. The token is read to make an HTTP request and goes nowhere else, so it never appears in a run record, an exported dataset or a log. Both stores are queried read-only, so a console pointed at the wrong one cannot damage it.

Nothing else about the posture changed. A `secret:` parameter is still masked everywhere it would be written down, a vault password typed at a prompt still reaches the process and nothing else, and git credentials are still never asked for or stored: a clone uses whatever `git` already has.

## What the console writes

| Path | What |
|---|---|
| `~/.local/state/ordane/runs.jsonl` | The run index, append-only. A finished run is a second record, never an edit |
| `~/.local/state/ordane/output/<id>.log` | The redacted output of one run |
| the DORA event log | A `*.started` before a deploy or cutover, and a `*.succeeded` or `*.failed` after |
| `<repo>/.ordane.yml` | One line only: `environments.allow`, from *Choose environments…*. Nothing else in that file is rewritten |
| `<repo>/inventory/<name>/aws_ec2.yml` | An EC2 inventory, when you ask for one. It holds no credential, only regions, tags and optionally a profile name |
| `~/.config/ordane/stores.env` | Where the two shared stores are, and the token and password for them. Created mode `0600`, and an existing file is tightened to it |

## Reporting something

Open an issue, or just say so. This is a workstation tool with one operator, so there is no embargo process to observe.