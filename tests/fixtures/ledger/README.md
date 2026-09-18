# Where this ledger came from

`written-by-audit-log.audit.jsonl` was not written by anything in this repository. It is the output of `bin/audit-log` in the deploy playbook Ordane reads for, captured from a real deploy so that the reader is tested against the writer rather than against our idea of it.

That makes it a frozen copy of somebody else's format. If the writer changes how it canonicalises a record, every ledger in production starts reading as broken and this fixture keeps passing, because it was written under the old rule.

## What holds the two together

Two checks in `tests/test_ledger.py` use this file:

- `test_the_hash_is_the_writers_hash_for_every_record` recomputes each record's hash with our own `record_hash` and compares it to the one the writer put there. That is the rule itself, checked against real output.
- `test_a_ledger_the_playbook_wrote_verifies_here` checks the whole chain, its length and its head.

Neither can see a change made to the writer after this file was captured. What closes that is `ORDANE_PLAYBOOK`, below.

## Checking against the writer as it is today

Point the suite at a checkout of the playbook and it loads the real tool and asks it to hash a record:

```bash
ORDANE_PLAYBOOK=/path/to/the-playbook uv run pytest -k writer
```

Without it that check skips, because the playbook is a separate project and somebody cloning Ordane has no reason to have it.

## Regenerating this file

Run a deploy through the playbook against a fleet you own, then copy the ledger it wrote. Do not hand-edit this file: every record's hash covers the record before it, so one edited character makes the rest unreadable, which is the property the whole feature rests on.
