import pytest

from ordane.web import security

PORT = 8710


def headers(**kwargs):
    return {k.replace("_", "-"): v for k, v in kwargs.items()}


@pytest.mark.parametrize("host", ["127.0.0.1:8710", "localhost:8710", "[::1]:8710"])
def test_loopback_hosts_on_the_served_port_are_accepted(host):
    assert security.host_is_loopback(host, PORT)


@pytest.mark.parametrize("host", ["example.com:8710", "127.0.0.1:9999", "", "192.168.1.5:8710"])
def test_other_hosts_are_refused(host):
    assert not security.host_is_loopback(host, PORT)


def test_a_get_from_loopback_is_allowed():
    assert security.check("GET", headers(host="127.0.0.1:8710"), PORT) == ""


def test_a_post_from_another_origin_is_refused():
    refusal = security.check(
        "POST",
        headers(host="127.0.0.1:8710", origin="https://evil.example"),
        PORT,
    )
    assert "not permitted" in refusal


def test_a_post_from_our_own_origin_is_allowed():
    assert (
        security.check(
            "POST",
            headers(host="127.0.0.1:8710", origin="http://127.0.0.1:8710"),
            PORT,
        )
        == ""
    )


def test_a_post_with_no_origin_at_all_is_refused():
    assert security.check("POST", headers(host="127.0.0.1:8710"), PORT) != ""


def test_a_rebound_dns_name_is_refused_even_with_a_loopback_origin():
    refusal = security.check(
        "POST",
        headers(host="attacker.test:8710", origin="http://127.0.0.1:8710"),
        PORT,
    )
    assert "Host header" in refusal
