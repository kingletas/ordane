"""Builds an inventory that asks EC2, by writing the plugin config Ansible reads.

`amazon.aws.aws_ec2` already queries EC2 and already uses boto3's whole
credential chain, so this writes it a file rather than becoming a second client
the console would have to hold credentials for.

The file is `inventory/<environment>/aws_ec2.yml`. It goes in a directory
because Ansible detects the plugin by filename, and `-i inventory/production`
reads a directory, which keeps the environment named `production`.

No credential is ever written. A profile is a name and is allowed; a key and a
secret are what the plugin's own credential chain is for.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

FILE_NAME = "aws_ec2.yml"
PLUGIN = "amazon.aws.aws_ec2"

# The collection that carries the plugin. Named so a control plane can be told
# what to install rather than left with "failed to parse".
COLLECTION = "amazon.aws"

# An AWS region, a profile name and a tag key are all written into a file that
# Ansible reads and then hands to an API. Each is checked rather than trusted.
REGION = re.compile(r"^[a-z]{2}(-[a-z]+)+-\d$")
PROFILE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
TAG_KEY = re.compile(r"^[A-Za-z0-9 +\-=._:/@]{1,128}$")
TAG_VALUE = re.compile(r"^[A-Za-z0-9 +\-=._:/@*?]{0,256}$")

# The two the plugin accepts inline, and the reason this refuses them.
CREDENTIAL_KEYS = ("aws_access_key", "aws_secret_key", "aws_security_token")


class AwsInventoryError(ValueError):
    """The inventory could not be described, or could not be written."""


@dataclass(frozen=True)
class Spec:
    """What to ask EC2 for, and how to group what comes back."""

    regions: tuple[str, ...] = ()
    # Tag name whose value becomes the group. `Role` is the usual one, and it
    # is what makes an inventory read like the estate rather than like EC2.
    group_by_tag: str = "Role"
    # Only instances carrying this tag. Empty means every running instance.
    filter_tag: str = ""
    filter_value: str = ""
    # A named profile from ~/.aws/config. Never a key, never a secret.
    profile: str = ""
    # Whether to reach hosts on their private address. True for anything
    # inside a VPC, which is nearly everything worth deploying to.
    private_addresses: bool = True
    extra_notes: tuple[str, ...] = field(default_factory=tuple)

    def validated(self) -> Spec:
        """The same spec, or a refusal naming the field that is wrong."""
        if not self.regions:
            raise AwsInventoryError("name at least one region")
        for region in self.regions:
            if not REGION.match(region):
                raise AwsInventoryError(f"{region!r} is not a region name, such as us-east-1")
        if not TAG_KEY.match(self.group_by_tag or ""):
            raise AwsInventoryError(f"{self.group_by_tag!r} is not a tag name")
        if self.filter_tag and not TAG_KEY.match(self.filter_tag):
            raise AwsInventoryError(f"{self.filter_tag!r} is not a tag name")
        if self.filter_value and not TAG_VALUE.match(self.filter_value):
            raise AwsInventoryError(f"{self.filter_value!r} is not a tag value")
        if self.profile and not PROFILE.match(self.profile):
            raise AwsInventoryError(f"{self.profile!r} is not a profile name")
        return self


def render(spec: Spec) -> str:
    """The plugin configuration, as somebody would want to read it later."""
    spec = spec.validated()
    lines = [
        "# Asks EC2 what is running, every time this environment is used.",
        "#",
        "# Read by Ansible, not by the console: `ansible-inventory -i <this",
        "# directory> --list` is what both of them call. Edit it freely.",
        "#",
        f"# Needs the {COLLECTION} collection and boto3. Credentials come from",
        "# the usual chain -- environment, profile, instance role, SSO -- and",
        "# none is written here.",
        "",
        f"plugin: {PLUGIN}",
        "",
        "regions:",
    ]
    lines += [f"  - {one}" for one in spec.regions]

    lines += [
        "",
        "# Only instances that are running. A stopped host is not a host.",
        "filters:",
        "  instance-state-name: running",
    ]
    if spec.filter_tag:
        value = spec.filter_value or "*"
        lines.append(f"  tag:{spec.filter_tag}: {value}")

    lines += [
        "",
        f"# Every instance tagged `{spec.group_by_tag}` joins the group of that name,",
        "# so `web` here means what `web` means everywhere else in this repository.",
        "keyed_groups:",
        f"  - key: tags.{spec.group_by_tag}",
        '    prefix: ""',
        '    separator: ""',
        "",
        "# What a host is called in the output, and what it is reached on.",
        "hostnames:",
        "  - tag:Name",
        "  - private-ip-address" if spec.private_addresses else "  - public-ip-address",
        "",
        "compose:",
        "  ansible_host: private_ip_address"
        if spec.private_addresses
        else "  ansible_host: public_ip_address",
    ]
    if spec.profile:
        lines += ["", f"aws_profile: {spec.profile}"]
    lines += [one for one in spec.extra_notes]
    return "\n".join(lines) + "\n"


def path_for(repo: Path, environment: str) -> Path:
    """Where this environment's plugin config goes."""
    return repo / "inventory" / environment / FILE_NAME


def write(repo: Path, environment: str, spec: Spec, *, force: bool = False) -> Path:
    """Writes the plugin config, refusing to replace a file somebody authored."""
    if not environment or "/" in environment or environment.startswith("."):
        raise AwsInventoryError(f"{environment!r} is not an environment name")
    body = render(spec)
    target = path_for(repo, environment)
    if target.exists() and not force:
        raise AwsInventoryError(f"{target} already exists")
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8")
    except OSError as exc:
        raise AwsInventoryError(f"could not write {target}: {exc}") from exc
    return target
