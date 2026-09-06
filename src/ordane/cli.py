"""Command line entry point.

Every subcommand except `serve` runs the console in a terminal, against the
same catalogue, config, metrics and store the web pages use.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .core import catalog as catalog_module
from .core import command as command_module
from .core import config as config_module
from .core import doctor as doctor_module
from .core import driver, identity, plane, recent, repository, source, starter, validation
from .core import inventory as inventory_module
from .core import runbook as runbook_module
from .insight import export, metrics, relaunch, sources
from .presentation.text import sentence
from .record import checks, decisions
from .record.runner import Runner, RunnerError
from .record.store import RunStore
from .terminal import console as terminal

DEFAULT_PORT = 8710
DEFAULT_STATE = Path.home() / ".local" / "state" / "ordane"
DEFAULT_EVENTS = Path.home() / ".local" / "state" / "dora" / "deployments.jsonl"
DEFAULT_HISTORY = "docs/dora/history.csv"

EXAMPLES = """
first time here:
  ordane clone https://github.com/you/control-plane.git --into ~/src
  ordane init --repo ~/some/control-plane
      writes a starting .ordane.yml from what it finds in the repository

  ordane doctor --repo ~/control-plane
      checks the repository and says what to do about anything it finds

  ordane --repo ~/control-plane
      opens the desktop console; `app` is the default, so the word is optional

everything the console shows is also here:
  ordane status  --repo PATH        the dashboard
  ordane actions --repo PATH        every target, grouped, with its parameters
  ordane runs    --repo PATH        what has run, newest first
  ordane refs    --repo PATH        every branch and tag, newest first
  ordane use BRANCH --repo PATH     check out a ref, and say what it changed
  ordane checks  --repo PATH        run the control plane's own checks in a container
  ordane show last --repo PATH      one run: its result, its failures, its output

launching:
  ordane run ping --repo PATH -e docker
  ordane run deploy --repo PATH -e staging --set branch_name=main --check
  ordane again last --repo PATH --failed-hosts

the shared dataset: one history, in whichever shape a store reads:
  ordane export --repo PATH --format csv -o runs.csv
  ordane export --repo PATH --format influx | curl --data-binary @- ...
  ordane export --repo PATH --format cypher --everything

Nothing is launchable until an environment is named in `.ordane.yml`, which
is the state a fresh control plane fails into on purpose.
"""

BANNER = """
  ordane: local console for {repo}

  http://127.0.0.1:{port}

  Launchable environments: {envs}
"""


def _common(parser: argparse.ArgumentParser, *, state: bool = False) -> None:
    # Not required: with no argument the last repository opened is reopened,
    # which is the only way a desktop launcher can start this at all.
    parser.add_argument(
        "--repo", type=Path, help="the control-plane repository; omit to reopen the last one"
    )
    if state:
        parser.add_argument("--state-dir", type=Path, default=DEFAULT_STATE)
        parser.add_argument("--events", type=Path, default=DEFAULT_EVENTS, help="DORA event log")
        parser.add_argument("--history", default=DEFAULT_HISTORY, help="release CSV, repo-relative")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ordane",
        description="A console for an Ansible control plane, with or without a Makefile: "
        "on the desktop, "
        "in a browser, or in this terminal.",
        epilog=EXAMPLES,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    # Where it is running from, not only which version. This installs three
    # ways -- a wrapper in ~/bin, a Debian package, a flatpak -- and more than
    # one can be on a machine at once, with PATH deciding quietly between them.
    parser.add_argument(
        "--version",
        action="version",
        version=f"ordane {__version__}\n  running from {Path(__file__).resolve().parent}",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)
    # `ordane --repo X` means `ordane app --repo X`; see main().

    app = sub.add_parser("app", help="run the desktop console (the default)")
    _common(app, state=True)
    app.add_argument(
        "--page",
        choices=("dashboard", "actions", "runs"),
        default="dashboard",
        help="the view to open on",
    )

    serve = sub.add_parser("serve", help="run the web console instead")
    _common(serve, state=True)
    serve.add_argument("--port", type=int, default=DEFAULT_PORT)
    serve.add_argument("--open", action="store_true", help="open a browser window")

    status = sub.add_parser("status", help="print the dashboard here")
    _common(status, state=True)

    actions = sub.add_parser("actions", help="list every target, grouped")
    _common(actions)

    runs = sub.add_parser("runs", help="list recorded runs")
    _common(runs, state=True)
    runs.add_argument("-n", "--limit", type=int, default=20)

    show = sub.add_parser("show", help="show one run, its result and the tail of its output")
    _common(show, state=True)
    show.add_argument("run", help="a run id, or `last`")
    show.add_argument("--tail", type=int, default=40, help="output lines to print, 0 for none")

    run = sub.add_parser("run", help="launch a target here and stream it")
    _common(run, state=True)
    run.add_argument("target")
    run.add_argument("--environment", "-e", default="", help="omit for a fixed-environment target")
    run.add_argument("--set", action="append", default=[], metavar="K=V", help="a parameter")
    run.add_argument("--check", action="store_true", help="dry run, where the target supports it")
    run.add_argument("--yes", "-y", action="store_true", help="skip the confirmation")

    again = sub.add_parser("again", help="run a recorded run again")
    _common(again, state=True)
    again.add_argument("run", help="a run id, or `last`")
    again.add_argument(
        "--failed-hosts",
        action="store_true",
        help="limit it to the hosts that failed, where the run allows one",
    )
    again.add_argument("--yes", "-y", action="store_true", help="skip the confirmation")

    catalog = sub.add_parser("catalog", help="print the parsed catalogue, and exit")
    _common(catalog)

    cloner = sub.add_parser("clone", help="clone a control plane and report where it landed")
    cloner.add_argument("url", help="an https, ssh, git or file URL, or an absolute path")
    cloner.add_argument(
        "--into", type=Path, default=Path.cwd(), help="the folder to clone inside (default: here)"
    )
    cloner.add_argument("--name", default="", help="what to call the clone (default: from the URL)")

    refs_of = sub.add_parser("refs", help="every branch and tag of a control plane")
    _common(refs_of)
    refs_of.add_argument("--fetch", action="store_true", help="ask the remote first")

    use = sub.add_parser("use", help="check out a ref of a control plane")
    _common(use, state=True)
    use.add_argument("ref", help="a branch, a tag, or origin/<branch>")

    checks = sub.add_parser("checks", help="run this control plane's own checks in a container")
    _common(checks, state=True)

    init = sub.add_parser("init", help="write a starting .ordane.yml for this repository")
    _common(init)
    init.add_argument("--force", action="store_true", help="replace an existing file")

    dataset_out = sub.add_parser(
        "export", help="write the run history in a shape another store can read"
    )
    _common(dataset_out, state=True)
    dataset_out.add_argument(
        "--format", choices=export.FORMATS, default="jsonl", help="what to write"
    )
    dataset_out.add_argument("-o", "--output", type=Path, help="a file; the default is stdout")
    dataset_out.add_argument(
        "--everything",
        action="store_true",
        help="every control plane in the history, not only this one",
    )
    dataset_out.add_argument(
        "--runs-only",
        action="store_true",
        help="leave out the release log and the patch ledger, which are included by default",
    )

    check = sub.add_parser(
        "doctor",
        help="check this control plane and say what to do about anything found",
    )
    _common(check, state=True)

    return parser


def _resolve_repo(raw: Path | None, state_dir: Path) -> Path:
    if raw is None:
        remembered = recent.last(state_dir)
        if remembered is None:
            sys.exit(
                "ordane: no repository given and none remembered.\n"
                "  ordane --repo ~/control-plane\n"
                "  ordane doctor --repo PATH   checks one before you open it"
            )
        return remembered
    repo = raw.expanduser().resolve()
    if not repo.is_dir():
        sys.exit(f"ordane: {repo} is not a directory")
    if not driver.drivable(repo):
        sys.exit(
            f"ordane: {repo} has neither a Makefile nor any playbooks, so there is nothing to drive"
        )
    return repo


def _catalog(repo: Path):
    try:
        cfg = config_module.load(repo)
        return catalog_module.build(repo, cfg), cfg
    except (catalog_module.CatalogError, config_module.ConfigError) as exc:
        sys.exit(f"ordane: {exc}")


def _store(args) -> RunStore:
    store = RunStore(args.state_dir.expanduser())
    store.prepare()
    return store


def _snapshot(args, repo: Path, cfg, runs: list) -> metrics.Snapshot:
    return metrics.snapshot(
        history_path=repo / args.history,
        events_path=args.events.expanduser(),
        runs=runs,
        slo_specs=cfg.slos,
        scope=cfg.metric_environments,
    )


def _pairs(assignments: list[str]) -> dict[str, str]:
    params: dict[str, str] = {}
    for item in assignments:
        key, sep, value = item.partition("=")
        if not sep:
            sys.exit(f"ordane: --set expects K=V, got {item!r}")
        params[key.strip()] = value.strip()
    return params


def _hosts_in(repo: Path, cat, environment: str) -> tuple:
    """Every host an environment holds, or none when it cannot be read.

    A policy on host count cannot be checked against an inventory nothing
    could read, and refusing on that basis would be refusing on a guess.
    """
    found = cat.environment(environment) if hasattr(cat, "environment") else None
    where = getattr(found, "inventory", "") if found else ""
    if not where:
        return ()
    return inventory_module.read(repo, where).hosts


def _launch(args, repo: Path, cat, cfg) -> int:
    target = cat.target(args.target)
    if target is None:
        known = ", ".join(t.name for t in cat.targets)
        sys.exit(f"ordane: unknown target {args.target!r}\n  known: {known}")

    try:
        environment = command_module.validate_environment(
            cat, target.fixed_environment or args.environment
        )
        params = command_module.validate_params(target, _pairs(args.set), cat, repo)
        built = command_module.for_target(
            target=target,
            environment=environment,
            params=params,
            config=cfg,
            dry_run=args.check,
            catalog=cat,
        )
    except command_module.ValidationError as exc:
        sys.exit(f"ordane: {exc}")

    # The same refusals the window applies. A policy enforced on one front end
    # and not another is worse than no policy: somebody relies on it, and the
    # terminal is where a deploy gets run when the window is inconvenient.
    refused = runbook_module.refusals(
        cfg.runbook_for(target.name),
        hosts=len(_hosts_in(repo, cat, environment)),
        ref=repository.read(repo).branch,
        dirty=repository.read(repo).dirty,
    )
    if refused and not args.check:
        # Every broken policy at once: fixing one and being refused again is
        # how somebody stops reading the reason.
        print(f"ordane: {target.name} was refused by this control plane's own policy")
        for one in refused:
            print(f"  {one.reason}")
            if one.detail:
                print(f"    {one.detail}")
        return 2

    print(f"{terminal.BOLD}{built.display}{terminal.OFF}")
    if target.danger != "low" and not args.yes:
        prompt = f"Run {args.target} against {environment}? type the environment name: "
        try:
            if input(prompt).strip() != environment:
                return print("cancelled") or 1
        except (EOFError, KeyboardInterrupt):
            return print("\ncancelled") or 1

    store = _store(args)
    runner = Runner(
        store,
        repo,
        args.events.expanduser(),
        plane=plane.of(repo, cfg.control_plane).name,
        lock_scope=cfg.lock_scope,
    )
    try:
        active = runner.start(
            kind="target",
            name=target.name,
            environment=environment,
            params=params,
            command=built,
            labels=cfg.labels_for(target.name),
            builder=_builder_for(repo, cat, environment),
        )
    except RunnerError as exc:
        sys.exit(f"ordane: {exc}")

    print(f"{terminal.DIM}run {active.id}{terminal.OFF}\n")
    return terminal.follow(active)


def _again(args, repo: Path, cfg, store: RunStore, run) -> int:
    """Runs a recorded run again, from what it recorded."""
    replay = relaunch.against_failures(run) if args.failed_hosts else relaunch.again(run)
    if not replay.possible:
        sys.exit(f"ordane: {replay.refusal}")

    print(f"{terminal.BOLD}{replay.command.safe_display}{terminal.OFF}")
    if replay.limited_to:
        print(f"{terminal.DIM}limited to {', '.join(replay.limited_to)}{terminal.OFF}")
    if not args.yes:
        prompt = f"Run {run.name} against {run.environment} again? type the environment name: "
        try:
            if input(prompt).strip() != run.environment:
                return print("cancelled") or 1
        except (EOFError, KeyboardInterrupt):
            return print("\ncancelled") or 1

    runner = Runner(
        store,
        repo,
        args.events.expanduser(),
        plane=plane.of(repo, cfg.control_plane).name,
        lock_scope=cfg.lock_scope,
    )
    try:
        active = runner.start(
            kind=run.kind,
            name=run.name,
            environment=run.environment,
            params=run.params,
            command=replay.command,
            labels=run.labels,
        )
    except RunnerError as exc:
        sys.exit(f"ordane: {exc}")
    print(f"{terminal.DIM}run {active.id}{terminal.OFF}\n")
    return terminal.follow(active)


def _checks(repo: Path, cfg, state_dir: Path) -> int:
    """Runs the suite the control plane declared, printing each as it finishes."""
    suite = cfg.validation
    why = validation.available(suite)
    if why:
        print(f"ordane: {why}", file=sys.stderr)
        return 1
    print(f"{terminal.BOLD}{len(suite.checks)} check(s) in {suite.image}{terminal.OFF}")
    print("  read-only, no network, as this user\n")

    def say(result) -> None:
        mark = "ok  " if result.ok else "FAIL"
        print(f"{mark}  {result.seconds:>6.1f}s  {result.check.name}")

    report = validation.run(repo, suite, on_result=say)
    # Recorded like anything else that ran: a suite that passed before a deploy
    # is evidence, and evidence nobody wrote down is a claim.
    written = checks.record(
        RunStore(state_dir),
        report,
        suite=suite,
        plane=plane.of(repo, cfg.control_plane).name,
        repo=repo,
    )
    print(f"\n{report.summary}  ·  recorded as {written.id}")
    for failed in report.failed:
        print(f"\n--- {failed.check.name}: {failed.check.display}")
        print(failed.output or "(printed nothing)")
    return 0 if report.ok else 1


def _builder_for(repo: Path, cat, environment: str) -> str:
    """The host that builds for this environment, or nothing when it cannot be read.

    Blocking here is what a terminal does. The desktop asks the same question
    on a thread, because a window may not wait on a cloud API.
    """
    found = cat.environment(environment)
    if found is None or not found.inventory:
        return ""
    answer = inventory_module.read(repo, found.inventory)
    group = answer.group("builder") if answer.known else None
    return ", ".join(group.hosts) if group else ""


def _clone(args) -> int:
    done = source.clone(args.url, args.into.expanduser().resolve(), args.name)
    if done.failed:
        print(f"ordane: {done.message}", file=sys.stderr)
        if done.detail:
            print(f"  {done.detail}", file=sys.stderr)
        return 1
    print(done.message)
    print(f"\n  ordane doctor --repo {done.detail}")
    return 0


def _refs(args, repo: Path) -> int:
    if args.fetch:
        fetched = source.fetch(repo)
        if fetched.failed:
            print(f"ordane: {fetched.message} {fetched.detail}".rstrip(), file=sys.stderr)
    found = source.refs(repo)
    if not found:
        print(f"ordane: {repo} is not a git checkout", file=sys.stderr)
        return 1
    for ref in found:
        mark = "*" if ref.current else " "
        print(f"{mark} {ref.name:<34} {ref.when}  {ref.commit}  {ref.subject}")
    return 0


def _use(args, repo: Path, state_dir: Path) -> int:
    """A ref carries its own configuration, so this says what it did to the gate."""
    before = _allowed(repo)
    done = source.switch(repo, args.ref)
    if done.failed:
        print(f"ordane: {done.message}", file=sys.stderr)
        if done.detail:
            print(f"  {done.detail}", file=sys.stderr)
        return 1
    print(done.message)
    after = _allowed(repo)
    widened = sorted(after - before)
    decisions.DecisionStore(state_dir).record(
        kind=decisions.REF,
        # The declared name, or a decision lands under a control plane nobody
        # is looking at. `use` runs before the catalogue is read, so the config
        # is read quietly here rather than not at all.
        plane=plane.of(repo, config_module.load_quietly(repo).control_plane).name,
        summary=f"Switched to {args.ref}"
        + (f", which allows {', '.join(widened)}" if widened else ""),
        detail={"ref": args.ref, "widened": widened, "allowed": sorted(after)},
    )
    if widened:
        print(f"\n  this ref allows {', '.join(widened)}, which the one before it did not")
    return 0


def _allowed(repo: Path) -> set[str]:
    """Which environments this ref would let a run reach. Empty when it will not parse."""
    try:
        cat, _cfg = _catalog(repo)
    except SystemExit:
        return set()
    return {e.name for e in cat.launchable_environments}


def _warn_if_root() -> None:
    """Said before anything else, on stderr, every time. Not a refusal.

    A console that quietly runs deployments as root is worse than one that
    refuses, because nobody finds out until the run history is a file their own
    account can no longer write.
    """
    actor = identity.who()
    if not actor.is_root:
        return
    rule = "!" * 72
    print(
        f"\n{terminal.RED}{rule}\n  RUNNING AS ROOT: {actor.summary}\n{rule}{terminal.OFF}\n"
        f"  {identity.ROOT_WARNING}\n",
        file=sys.stderr,
    )


def _desktop_findings() -> list:
    """The desktop's own check, when the desktop package can be imported at all."""
    try:
        from .desktop.availability import finding
    except ImportError:
        return []
    return [finding()]


def _app(args, repo: Path) -> int:
    try:
        from .desktop.app import Settings, run
    except (ImportError, ValueError) as exc:
        sys.exit(
            f"ordane: the desktop app needs GTK 4 and libadwaita ({exc}).\n"
            "  On Ubuntu: sudo apt install python3-gi gir1.2-gtk-4.0 gir1.2-adw-1\n"
            "  Every view is also available in this terminal: ordane status --repo ..."
        )
    return run(
        Settings(
            repo=repo,
            state_dir=args.state_dir.expanduser(),
            events_path=args.events.expanduser(),
            history=args.history,
            page=getattr(args, "page", "dashboard"),
        )
    )


def _serve(args, repo: Path, cat, cfg) -> int:
    try:
        import uvicorn

        from .web import Settings, create_app
    except ImportError as exc:
        # The Debian package ships the desktop and the terminal, and leaves the
        # web front end's dependencies out. Saying which ones are missing beats
        # a traceback about a module nobody asked for by name.
        print("ordane: the browser front end needs a web stack that is not installed here.")
        print(f"  missing: {exc.name or exc}")
        print("  pip install fastapi uvicorn jinja2 python-multipart")
        print("\n  Every view is also in this terminal: ordane status, actions, runs, show.")
        return 2

    settings = Settings(
        repo=repo,
        port=args.port,
        state_dir=args.state_dir.expanduser(),
        history_path=repo / args.history,
        events_path=args.events.expanduser(),
    )
    launchable = ", ".join(e.name for e in cat.launchable_environments) or "none (read-only)"
    print(BANNER.format(repo=repo, port=args.port, envs=launchable))
    if not cfg.allow_environments:
        print("  No environment is allow-listed, so nothing can be launched.")
        print(f"  Add `environments: {{ allow: [...] }}` to {repo}/.ordane.yml\n")

    if args.open:
        import webbrowser

        webbrowser.open(f"http://127.0.0.1:{args.port}")

    uvicorn.run(
        create_app(settings),
        host="127.0.0.1",
        port=args.port,
        log_level="warning",
        access_log=False,
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    raw = list(sys.argv[1:] if argv is None else argv)
    # `ordane`, `ordane --repo X` and `ordane app --repo X` all
    # mean the same thing. The first is what a desktop launcher runs.
    if not raw:
        raw = ["app"]
    elif raw[0].startswith("-") and not ({"--help", "-h", "--version"} & set(raw)):
        raw.insert(0, "app")
    args = _parser().parse_args(raw)
    _warn_if_root()

    # Cloning has no control plane to resolve yet: it is what produces one.
    if args.cmd == "clone":
        return _clone(args)

    state_dir = getattr(args, "state_dir", DEFAULT_STATE).expanduser()
    repo = _resolve_repo(args.repo, state_dir)
    recent.remember(state_dir, repo)

    # The doctor is the one command that must work on a repository the others
    # refuse: a control plane it cannot parse is exactly what it is for.
    if args.cmd == "doctor":
        report = doctor_module.examine(
            repo,
            history=repo / args.history,
            events=args.events.expanduser(),
            extra=_desktop_findings(),
        )
        terminal.checkup(report, repo)
        return 0 if report.healthy else 1

    # These two read and write git, and say nothing about what `make help`
    # prints: a control plane on a ref that will not parse is exactly when
    # somebody needs to change ref.
    if args.cmd == "refs":
        return _refs(args, repo)
    if args.cmd == "use":
        return _use(args, repo, state_dir)

    cat, cfg = _catalog(repo)

    if args.cmd == "checks":
        return _checks(repo, cfg, state_dir)

    if args.cmd == "init":
        try:
            written = starter.write(repo, cat, force=args.force)
        except starter.StarterExists as exc:
            sys.exit(f"ordane: {exc}\n  pass --force to replace it")
        print(f"wrote {written}")
        print(f"  {len(cat.targets)} target(s) from {cat.discovery.target_source}")
        print(f"  environments from {cat.discovery.environment_source}")
        print("\nNothing is launchable yet. Uncomment an environment under `allow`, then:")
        print(f"  ordane doctor --repo {repo}")
        return 0

    if args.cmd == "app":
        return _app(args, repo)

    if args.cmd == "serve":
        return _serve(args, repo, cat, cfg)

    if args.cmd == "run":
        return _launch(args, repo, cat, cfg)

    if args.cmd == "actions":
        terminal.actions(cat, cfg)
        return 0

    if args.cmd == "catalog":
        print(f"repository: {repo}")
        print(f"\nenvironments ({len(cat.environments)}):")
        for env in cat.environments:
            note = env.blocked_reason
            print(f"  {env.name:<16}{'blocked: ' + note if note else 'launchable'}")
        print(f"\ntargets ({len(cat.targets)}):")
        for target in cat.targets:
            print(
                f"  [{target.danger:<6}] {target.group:<12} {target.name:<22} {target.description}"
            )
        print(f"\nplaybooks ({len(cat.playbooks)}):")
        for playbook in cat.playbooks:
            print(f"  {playbook.path}")
        return 0

    store = _store(args)
    runs = store.all(repo, plane=plane.of(repo, cfg.control_plane).name)

    if args.cmd == "status":
        terminal.dashboard(cat, _snapshot(args, repo, cfg, runs), runs, repo)
        return 0

    if args.cmd == "export":
        wanted = store.all() if args.everything else runs
        named = plane.of(repo, cfg.control_plane).name
        backfill = sources.Backfill() if args.runs_only else sources.read(repo)
        for note in backfill.notes:
            print(f"  note: {note}", file=sys.stderr)
        rendered = export.render(wanted, args.format, backfill.releases, backfill.patches, named)
        if args.output:
            args.output.expanduser().write_text(rendered, encoding="utf-8")
            held = [f"{len(wanted)} run(s)"]
            if backfill.releases:
                held.append(f"{len(backfill.releases)} release(s)")
            if backfill.patches:
                held.append(f"{len(backfill.patches)} patch event(s)")
            print(
                f"wrote {sentence(held)} to {args.output}: {export.WHAT_EACH_IS[args.format]}",
                file=sys.stderr,
            )
        else:
            sys.stdout.write(rendered)
        return 0

    if args.cmd == "runs":
        terminal.history(runs, args.limit)
        return 0

    if args.cmd == "again":
        wanted = runs[0] if args.run == "last" and runs else store.get(args.run)
        if wanted is None:
            sys.exit(f"ordane: no run {args.run!r}")
        return _again(args, repo, cfg, store, wanted)

    if args.cmd == "show":
        wanted = runs[0] if args.run == "last" and runs else store.get(args.run)
        if wanted is None:
            sys.exit(f"ordane: no run {args.run!r}")
        terminal.run_detail(wanted, store.output(wanted.id), args.tail)
        return 0

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
