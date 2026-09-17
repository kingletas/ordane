"""The deploy ledger, printed: every deploy in one line, or one deploy in full."""

from __future__ import annotations

from ..insight import ledger
from ..presentation import language
from ..presentation.text import moment, plural
from .console import BLUE, BOLD, DIM, GREEN, OFF, RED, YELLOW, heading

LEVEL_MARK = {
    language.OK: f"{GREEN}✓{OFF}",
    language.ATTENTION: f"{YELLOW}!{OFF}",
    language.PROBLEM: f"{RED}✗{OFF}",
    language.UNKNOWN: f"{DIM}·{OFF}",
}

OUTCOME_COLOUR = {
    ledger.SUCCEEDED: GREEN,
    ledger.BUILT_ONLY: GREEN,
    ledger.FINISHED: BLUE,
    ledger.FAILED: RED,
    ledger.STOPPED: RED,
    ledger.UNFINISHED: YELLOW,
}


def books(found: list[ledger.Book], limit: int) -> None:
    """Each ledger's chain, then its newest deploys."""
    if not found:
        print("\nNo deploy ledger found.")
        print(f"  {DIM}Name one under `ledgers:` in .ordane.yml, or pass --ledger PATH.{OFF}")
        return
    for book in found:
        chain = book.chain
        heading(f"{book.environment or 'Ledger'}  {DIM}{book.source.path}{OFF}")
        _chain_line(book)
        if book.source.note:
            print(f"  {YELLOW}{book.source.note}{OFF}")
        for deployment in book.deployments[:limit]:
            outcome = language.ledger_outcome(deployment.outcome)
            colour = OUTCOME_COLOUR.get(deployment.outcome, "")
            approver = deployment.approval.signer if deployment.approval else "no approval"
            mark = "" if deployment.trusted else f" {RED}untrusted{OFF}"
            print(
                f"  {moment(deployment.started_at):<20} {colour}{outcome.name:<19}{OFF}"
                f" {deployment.release:<32} {deployment.deployer.name}"
                f" {DIM}approved: {approver}{OFF}{mark}"
            )
        _timings(book)
        hidden = len(book.deployments) - limit
        if hidden > 0:
            print(f"  {DIM}and {plural(hidden, 'older deploy')}{OFF}")
        if chain.entries and not book.deployments:
            print(f"  {DIM}No deploys in it yet.{OFF}")


def deployment(book: ledger.Book, chosen: ledger.Deployment) -> None:
    """One deploy: the answers a reviewer asks for, then the flow that backs them."""
    print(f"\n{BOLD}{chosen.release or 'Deploy'}{OFF} {DIM}— {book.environment}{OFF}")
    _chain_line(book)

    heading("What the records say")
    for answer in ledger.answers(chosen, book.chain):
        mark = LEVEL_MARK.get(answer.level, " ")
        print(f"  {mark} {answer.question:<36} {BOLD}{answer.answer}{OFF}")
        if answer.detail:
            print(f"    {'':<36} {DIM}{answer.detail}{OFF}")

    heading("How long it took")
    for key, seconds in chosen.spans.items():
        mark = f"{YELLOW}!{OFF}" if key == ledger.HEADLINE else " "
        print(f"  {mark} {language.span_name(key):<20} {BOLD}{ledger.spoken(seconds)}{OFF}")
    if not chosen.spans:
        print(f"  {DIM}Nothing in this deploy has two records to measure between.{OFF}")

    heading("How it went")
    for step in ledger.steps(chosen):
        mark = LEVEL_MARK.get(step.level, " ")
        who = f" {YELLOW}{step.role} {step.who}{OFF}" if step.worth_naming else ""
        broken = "" if step.trusted else f" {RED}(after the break){OFF}"
        print(
            f"  {mark} {moment(step.at):<20} {step.name:<18} {DIM}{step.detail}{OFF}{who}{broken}"
        )

    exact = [value for answer in ledger.answers(chosen, book.chain) for value in answer.exact]
    if exact:
        heading("Exact values")
        for value in exact:
            print(f"  {value}")


def _chain_line(book: ledger.Book) -> None:
    chain = book.chain
    word = language.chain_state(chain.state)
    colour = {ledger.INTACT: GREEN, ledger.BROKEN: RED}.get(chain.state, YELLOW)
    said = word.meaning
    if chain.state == ledger.BROKEN:
        said = f"Line {chain.broken_line}: {chain.reason}. {word.meaning}"
    elif chain.state == ledger.INTACT:
        said = f"{plural(len(chain.entries), 'record')}, head {chain.head[:16]}…"
    print(f"  {colour}{word.name}{OFF}  {DIM}{said}{OFF}")


def _timings(book: ledger.Book) -> None:
    """What this ledger's deploys usually cost, printed under its list."""
    measured = [one for one in book.timings if one.measured]
    if not measured:
        return
    print()
    for timing in measured:
        over = f"over {plural(timing.samples, 'deploy')}"
        spread = (
            over
            if timing.fastest == timing.slowest
            else f"{ledger.spoken(timing.fastest)} to {ledger.spoken(timing.slowest)}, {over}"
        )
        print(
            f"  {timing.name:<20} {BOLD}{ledger.spoken(timing.typical):<14}{OFF}{DIM}{spread}{OFF}"
        )
