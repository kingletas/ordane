from ordane.record.redact import MASK, Redactor


def test_an_env_assignment_is_masked():
    out = Redactor().line("YOTTA_API_KEY=abc123def456ghi")
    assert "abc123def456ghi" not in out
    assert "YOTTA_API_KEY" in out and MASK in out


def test_an_exported_password_is_masked():
    assert "hunter2hunter2" not in Redactor().line("export PASSWORD=hunter2hunter2")


def test_a_yaml_style_secret_is_masked():
    assert "s3cr3t-value" not in Redactor().line("  slack_token: s3cr3t-value")


def test_an_aws_key_is_masked_wherever_it_appears():
    assert "AKIAIOSFODNN7EXAMPLE" not in Redactor().line("found AKIAIOSFODNN7EXAMPLE in output")


def test_a_url_password_is_masked():
    url = "postgres://user:swordfish@db.internal/app"  # pragma: allowlist secret
    assert "swordfish" not in Redactor().line(url)


def test_a_placeholder_is_left_alone_so_logs_stay_readable():
    assert Redactor().line("RDS_CLUSTER_ID=''") == "RDS_CLUSTER_ID=''"
    assert Redactor().line("COMPLETE_DEPLOYMENT=1") == "COMPLETE_DEPLOYMENT=1"


def test_ordinary_output_is_untouched():
    line = "TASK [Gathering Facts] ***********"
    assert Redactor().line(line) == line


def test_a_known_literal_is_masked_anywhere():
    redactor = Redactor(["correct-horse-battery"])
    assert "correct-horse-battery" not in redactor.line("the value was correct-horse-battery here")


def test_a_short_literal_is_ignored_so_common_words_survive():
    redactor = Redactor(["a", "0", "no"])
    assert redactor.line("no changes") == "no changes"


# --- a secret typed after the run started ---


def test_a_value_learned_mid_run_is_masked_from_then_on():
    redactor = Redactor()
    assert "hunter2000" in redactor.line("echoed: hunter2000")
    redactor.also("hunter2000")
    assert "hunter2000" not in redactor.line("echoed: hunter2000")


def test_something_too_short_or_obvious_is_not_learned():
    redactor = Redactor()
    for value in ("", "abc", "none", "true"):
        redactor.also(value)
    assert redactor.line("abc none true") == "abc none true"
