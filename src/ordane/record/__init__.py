"""What has happened: running a command, keeping its output, and saying so.

The layer that writes. Everything it stores is redacted first, and the run
index is append-only: a finished run is a second record, never an edit.
"""
