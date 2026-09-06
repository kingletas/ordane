"""Read-only clients for the two shared stores, over HTTP and nothing else.

InfluxDB answers Flux over HTTP and Neo4j answers Cypher over HTTP, so both are
a `urllib` call away and neither needs a driver installed.

Nothing here can write to a store: the console exports a file somebody loads, so
one pointed at the wrong store cannot damage it.

Settings come from `~/.config/ordane/stores.env`, or the environment, which
wins. Always write that file through `write_settings_file`, which creates it
`0600` and tightens an existing one: a common umask would leave a token readable
by every account on the machine.
"""

from __future__ import annotations

import base64
import csv
import io
import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

# Long enough for a query over a few hundred thousand points, short enough that
# a store which is not there does not hold the interface.
TIMEOUT_SECONDS = 10

PREFIX = "ORDANE_"

# Where the settings live when they are not in the environment. Config rather
# than state: it is a thing a person writes, not a thing the console keeps.
FILE_NAME = "stores.env"

TEMPLATE = """# Where ordane reads the shared stores. This file is read and never
# written: put the values in yourself, and nothing here will change them.
#
# Point these at wherever the stores actually run. Neither has to exist:
# a store that answers nothing shows as unconfigured rather than as empty.

ORDANE_INFLUX_URL=http://localhost:8086
ORDANE_INFLUX_TOKEN=
ORDANE_INFLUX_ORG=estate
ORDANE_INFLUX_BUCKET=runs

ORDANE_NEO4J_URL=http://localhost:7474
ORDANE_NEO4J_USER=neo4j
ORDANE_NEO4J_PASSWORD=
"""


def settings_path() -> Path:
    """`~/.config/ordane/stores.env`, or wherever XDG says config goes."""
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "ordane" / FILE_NAME


@dataclass(frozen=True)
class Answer:
    """Rows, or the reason there are none. Never an exception into a view."""

    rows: list[dict] = field(default_factory=list)
    error: str = ""

    @property
    def ok(self) -> bool:
        return not self.error

    def column(self, name: str) -> list:
        return [row.get(name) for row in self.rows]


@dataclass(frozen=True)
class Stores:
    influx_url: str = ""
    influx_token: str = ""
    influx_org: str = "estate"
    influx_bucket: str = "runs"
    neo4j_url: str = ""
    neo4j_user: str = "neo4j"
    neo4j_password: str = ""

    @property
    def has_influx(self) -> bool:
        return bool(self.influx_url and self.influx_token)

    @property
    def has_neo4j(self) -> bool:
        return bool(self.neo4j_url and self.neo4j_password)

    @property
    def any(self) -> bool:
        return self.has_influx or self.has_neo4j

    def flux(self, query: str) -> Answer:
        """A Flux query, as rows. InfluxDB answers annotated CSV over HTTP."""
        if not self.has_influx:
            return Answer(error=f"no InfluxDB configured: set {PREFIX}INFLUX_URL and _TOKEN")
        url = f"{self.influx_url.rstrip('/')}/api/v2/query?org={self.influx_org}"
        body, error = _post(
            url,
            query.encode("utf-8"),
            {
                "Authorization": f"Token {self.influx_token}",
                "Content-Type": "application/vnd.flux",
                "Accept": "application/csv",
            },
        )
        return Answer(error=error) if error else Answer(rows=_annotated_csv(body))

    def cypher(self, query: str, parameters: dict | None = None) -> Answer:
        """A Cypher query, as rows. Neo4j answers JSON over its HTTP endpoint."""
        if not self.has_neo4j:
            return Answer(error=f"no Neo4j configured: set {PREFIX}NEO4J_URL and _PASSWORD")
        url = f"{self.neo4j_url.rstrip('/')}/db/neo4j/tx/commit"
        payload = json.dumps(
            {"statements": [{"statement": query, "parameters": parameters or {}}]}
        ).encode("utf-8")
        credentials = base64.b64encode(f"{self.neo4j_user}:{self.neo4j_password}".encode()).decode()
        body, error = _post(
            url,
            payload,
            {
                "Authorization": f"Basic {credentials}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        if error:
            return Answer(error=error)
        try:
            answer = json.loads(body)
        except ValueError as exc:
            return Answer(error=f"neo4j sent something that is not JSON: {exc}")
        problems = answer.get("errors") or []
        if problems:
            return Answer(error=problems[0].get("message", "neo4j refused the query"))
        return Answer(rows=_neo4j_rows(answer))


def read_settings_file(path: Path | None = None) -> dict:
    """The settings file, as a mapping. A missing or unreadable one is empty.

    One key at a time and nothing evaluated: this is a file of values, not a
    script, and treating it as one would be a way to run something by editing
    a configuration file.
    """
    path = path or settings_path()
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return {}
    values: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, value = line.partition("=")
        values[name.strip()] = value.strip().strip("\"'")
    return values


def configured(environment: dict | None = None, path: Path | None = None) -> Stores:
    """What the environment says, then what the file says.

    The environment wins, so a shell that has been pointed somewhere else for
    one run does not have to edit a file to do it.
    """
    from_file = read_settings_file(path)
    live = environment if environment is not None else dict(os.environ)
    merged = {**from_file, **{k: v for k, v in live.items() if v}}
    read = merged.get
    return Stores(
        influx_url=read(f"{PREFIX}INFLUX_URL", "") or "",
        influx_token=read(f"{PREFIX}INFLUX_TOKEN", "") or "",
        influx_org=read(f"{PREFIX}INFLUX_ORG", "") or "estate",
        influx_bucket=read(f"{PREFIX}INFLUX_BUCKET", "") or "runs",
        neo4j_url=read(f"{PREFIX}NEO4J_URL", "") or "",
        neo4j_user=read(f"{PREFIX}NEO4J_USER", "") or "neo4j",
        neo4j_password=read(f"{PREFIX}NEO4J_PASSWORD", "") or "",
    )


# Owner-only. A token in a group-readable file is a token every account on the
# machine can read, and a common umask makes that the default.
PRIVATE_MODE = 0o600

# What the settings file is allowed to hold. Anything else a caller passes is
# refused rather than written: this file is read back into the environment of
# nothing, but it is still a file whose keys somebody will assume are honoured.
KEYS = (
    f"{PREFIX}INFLUX_URL",
    f"{PREFIX}INFLUX_TOKEN",
    f"{PREFIX}INFLUX_ORG",
    f"{PREFIX}INFLUX_BUCKET",
    f"{PREFIX}NEO4J_URL",
    f"{PREFIX}NEO4J_USER",
    f"{PREFIX}NEO4J_PASSWORD",
)

SECRET_KEYS = (f"{PREFIX}INFLUX_TOKEN", f"{PREFIX}NEO4J_PASSWORD")


class SettingsError(ValueError):
    """The settings could not be written."""


def too_open(path: Path | None = None) -> str:
    """Who else can read the settings file, said in words, or nothing."""
    path = path or settings_path()
    try:
        mode = path.stat().st_mode & 0o777
    except OSError:
        return ""
    if not mode & 0o077:
        return ""
    who = []
    if mode & 0o070:
        who.append("everyone in the group")
    if mode & 0o007:
        who.append("every account on this machine")
    return f"{path} is mode {mode:04o}, {' and '.join(who)} can read it"


def write_settings_file(values: dict[str, str], path: Path | None = None) -> Path:
    """Writes the settings, owner-readable only, replacing whatever was there.

    Written to a temporary file in the same directory and renamed, so a failure
    part-way leaves the previous settings rather than half of the new ones.
    """
    unknown = sorted(set(values) - set(KEYS))
    if unknown:
        raise SettingsError(f"not a setting this file holds: {', '.join(unknown)}")

    path = path or settings_path()
    lines = [
        "# Where ordane reads the shared stores. Written by the console;",
        "# an environment variable of the same name overrides anything here.",
        "",
    ]
    lines += [f"{key}={values[key]}" for key in KEYS if values.get(key, "").strip()]
    body = "\n".join(lines) + "\n"

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.new")
        handle = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, PRIVATE_MODE)
        try:
            os.write(handle, body.encode("utf-8"))
        finally:
            os.close(handle)
        # Explicit, because O_CREAT respects the umask and an existing file
        # keeps whatever mode it already had.
        os.chmod(temporary, PRIVATE_MODE)
        os.replace(temporary, path)
    except OSError as exc:
        raise SettingsError(f"could not write {path}: {exc}") from exc
    return path


def _post(url: str, body: bytes, headers: dict) -> tuple[str, str]:
    """The response, or a sentence saying why there is not one."""
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")  # noqa: S310
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:  # noqa: S310
            return response.read().decode("utf-8", errors="replace"), ""
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:200].strip()
        return "", f"HTTP {exc.code}: {detail or exc.reason}"
    except urllib.error.URLError as exc:
        return "", f"cannot reach it: {exc.reason}"
    except (TimeoutError, OSError) as exc:
        return "", f"cannot reach it: {exc}"


def _annotated_csv(body: str) -> list[dict]:
    """InfluxDB's CSV, minus the annotation lines and its bookkeeping columns."""
    rows: list[dict] = []
    for block in body.split("\n\n"):
        lines = [line for line in block.splitlines() if line and not line.startswith("#")]
        if len(lines) < 2:
            continue
        for row in csv.DictReader(io.StringIO("\n".join(lines))):
            # `result` and `table` are Influx's own bookkeeping, and the empty
            # column is the leading comma every annotated row starts with.
            rows.append({k: v for k, v in row.items() if k not in ("", "result", "table")})
    return rows


def _neo4j_rows(answer: dict) -> list[dict]:
    results = answer.get("results") or []
    if not results:
        return []
    columns = results[0].get("columns") or []
    return [
        dict(zip(columns, entry.get("row") or [], strict=False))
        for entry in results[0].get("data") or []
    ]
