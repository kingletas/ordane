"""The EC2 inventory this console writes, checked by Ansible rather than by eye.

Nothing here reaches AWS. What is provable without an account is that the file
is what the plugin expects: Ansible loads it, recognises the plugin, and fails
on credentials rather than on syntax: which is the difference between a
configuration that is wrong and one that has simply not been given a key.
"""

from __future__ import annotations

import os
import shutil
import subprocess

import pytest
import yaml

from ordane.core import awsinventory

# Credentials deliberately unresolvable, so a test can never touch an account.
# Removed rather than blanked: boto3 reads AWS_PROFILE="" as a profile whose
# name is the empty string, and then fails about the profile instead.
UNSET = ("AWS_PROFILE", "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN")
NO_CREDENTIALS = {
    "AWS_CONFIG_FILE": "/dev/null",
    "AWS_SHARED_CREDENTIALS_FILE": "/dev/null",
    "AWS_EC2_METADATA_DISABLED": "true",
}


def without_credentials() -> dict:
    env = {k: v for k, v in os.environ.items() if k not in UNSET}
    env.update(NO_CREDENTIALS)
    return env


A_SPEC = awsinventory.Spec(regions=("us-east-1",), group_by_tag="Role")


def test_it_renders_valid_yaml():
    loaded = yaml.safe_load(awsinventory.render(A_SPEC))
    assert loaded["plugin"] == awsinventory.PLUGIN
    assert loaded["regions"] == ["us-east-1"]


def test_it_groups_by_the_tag_it_was_given():
    loaded = yaml.safe_load(
        awsinventory.render(awsinventory.Spec(regions=("eu-west-2",), group_by_tag="Tier"))
    )
    assert loaded["keyed_groups"][0]["key"] == "tags.Tier"


def test_it_only_asks_for_running_instances():
    loaded = yaml.safe_load(awsinventory.render(A_SPEC))
    assert loaded["filters"]["instance-state-name"] == "running"


def test_a_tag_filter_becomes_a_filter():
    spec = awsinventory.Spec(regions=("us-east-1",), filter_tag="Environment", filter_value="prod")
    loaded = yaml.safe_load(awsinventory.render(spec))
    assert loaded["filters"]["tag:Environment"] == "prod"


def test_private_addressing_is_the_default():
    loaded = yaml.safe_load(awsinventory.render(A_SPEC))
    assert loaded["compose"]["ansible_host"] == "private_ip_address"


def test_public_addressing_when_asked_for():
    spec = awsinventory.Spec(regions=("us-east-1",), private_addresses=False)
    loaded = yaml.safe_load(awsinventory.render(spec))
    assert loaded["compose"]["ansible_host"] == "public_ip_address"


# --- what it refuses, which is the half that matters ---


def test_no_credential_is_ever_written():
    """The plugin accepts a key and a secret inline. This never writes one."""
    spec = awsinventory.Spec(regions=("us-east-1",), profile="deployer")
    body = awsinventory.render(spec)
    for key in awsinventory.CREDENTIAL_KEYS:
        assert key not in body
    assert "aws_profile: deployer" in body, "a profile is a name, and is allowed"


def test_a_region_that_is_not_one_is_refused():
    with pytest.raises(awsinventory.AwsInventoryError):
        awsinventory.render(awsinventory.Spec(regions=("; rm -rf /",)))


def test_no_region_at_all_is_refused():
    with pytest.raises(awsinventory.AwsInventoryError):
        awsinventory.render(awsinventory.Spec())


def test_a_tag_name_that_is_not_one_is_refused():
    with pytest.raises(awsinventory.AwsInventoryError):
        awsinventory.render(
            awsinventory.Spec(regions=("us-east-1",), group_by_tag="a\nplugin: evil")
        )


def test_a_profile_that_is_not_a_name_is_refused():
    with pytest.raises(awsinventory.AwsInventoryError):
        awsinventory.render(awsinventory.Spec(regions=("us-east-1",), profile="../../etc/passwd"))


def test_an_environment_name_that_escapes_the_directory_is_refused(tmp_path):
    with pytest.raises(awsinventory.AwsInventoryError):
        awsinventory.write(tmp_path, "../elsewhere", A_SPEC)


def test_it_refuses_to_replace_a_file_somebody_wrote(tmp_path):
    awsinventory.write(tmp_path, "production", A_SPEC)
    with pytest.raises(awsinventory.AwsInventoryError):
        awsinventory.write(tmp_path, "production", A_SPEC)
    awsinventory.write(tmp_path, "production", A_SPEC, force=True)


def test_it_writes_a_directory_so_the_environment_keeps_its_name(tmp_path):
    written = awsinventory.write(tmp_path, "production", A_SPEC)
    assert written == tmp_path / "inventory" / "production" / "aws_ec2.yml"
    assert written.parent.is_dir()


# --- and the check nothing else can make: Ansible's own opinion of the file ---


@pytest.mark.skipif(
    shutil.which("ansible-inventory") is None, reason="ansible-inventory is not installed"
)
def test_ansible_recognises_it_as_the_ec2_plugin(tmp_path):
    """It must fail on credentials, not on syntax.

    A file Ansible cannot parse and a file it parses but cannot authenticate
    look identical from here: both are empty, and only one of them is a bug
    in what this console wrote.
    """
    awsinventory.write(tmp_path, "production", A_SPEC)
    result = subprocess.run(
        ["ansible-inventory", "--list", "-i", "inventory/production"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=120,
        env=without_credentials(),
        check=False,
    )
    complaint = " ".join(result.stderr.split())

    # Ansible's yaml inventory plugin says this when it meets a file that is a
    # plugin configuration rather than a static inventory. Seeing it proves the
    # file was recognised for what it is.
    assert "Plugin configuration YAML file" in complaint, (
        f"Ansible did not recognise it as a plugin config: {complaint[:400]}"
    )
    # And the plugin's own refusal must be about what it is short of rather
    # than about the file. Which thing it is short of depends on the machine:
    # with boto3 installed it gets as far as looking for credentials, and
    # without it, it stops at the import. CI has no boto3, so asserting only
    # the credentials wording failed there for a reason that says nothing
    # about what this test is for.
    short_of = ("credential", "botocore", "boto3")
    assert any(one in complaint.lower() for one in short_of), (
        f"expected the plugin to report what it lacks, got: {complaint[:400]}"
    )
    # What it must never say is that the file itself is wrong.
    for wrong in ("Syntax Error", "expected a dict", "could not be parsed"):
        assert wrong not in complaint, f"the written file is malformed: {complaint[:400]}"
