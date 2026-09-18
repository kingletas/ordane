"""The demo has to show the things the demo is for.

`make demo` is where somebody looks first, and a feature it cannot show is one
they have to take on trust. Every release in the seeded ledgers was unique
until the retry flag existed, so a release deployed twice, which is the whole
point of an attempt reference, could not be seen there at all.
"""

from __future__ import annotations

import importlib.machinery
import importlib.util
from collections import Counter
from pathlib import Path

from ordane.insight import ledger

ROOT = Path(__file__).resolve().parents[1]


def seeded(tmp_path: Path):
    """The demo ledgers, written into a directory of this test's own."""
    source = ROOT / "scripts" / "demo_ledger.py"
    loader = importlib.machinery.SourceFileLoader("demo_ledger", str(source))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module.write(tmp_path / "ledgers")


def test_the_demo_seeds_a_release_that_was_deployed_twice(tmp_path):
    written = seeded(tmp_path)
    attempts = Counter()
    for path in written:
        for deployment in ledger.deployments(ledger.read(path)):
            if deployment.release:
                attempts[deployment.release] += 1

    retried = [release for release, count in attempts.items() if count > 1]
    assert retried, "no release in the demo was deployed more than once"


def test_both_attempts_at_a_demo_release_can_be_addressed(tmp_path):
    """A reference each, or the earlier attempt has no way of being opened."""
    books = [
        ledger.Book(
            source=ledger.Source(path=path, environment="", origin=ledger.FLAG),
            chain=ledger.read(path),
            deployments=ledger.deployments(ledger.read(path)),
        )
        for path in seeded(tmp_path)
    ]
    counted = Counter(d.release for book in books for d in book.deployments if d.release)
    retried = [name for name, count in counted.items() if count > 1]
    assert retried, "no release in the demo was deployed more than once"
    release = retried[0]

    tries = ledger.attempts(books, release)

    assert len(tries) > 1
    assert len({one.ref for _, one in tries}) == len(tries), "two attempts share one reference"
    for _, one in tries:
        assert ledger.find(books, one.ref) is not None, f"{one.ref} reaches nothing"
    # The bare name still reaches the newest, which is what typing one means.
    newest = ledger.find(books, release)
    assert newest is not None and newest[1].ref == tries[-1][1].ref


def test_the_demo_ledgers_still_verify(tmp_path):
    """The quiet direction: a retry must not leave the chain looking tampered with."""
    for path in seeded(tmp_path):
        chain = ledger.read(path)
        assert chain.state == ledger.INTACT, f"{path.name} reads as {chain.state}"
        assert all(entry.trusted for entry in chain.entries)
