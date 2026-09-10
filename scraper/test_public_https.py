import pytest
from urllib.request import Request
from scraper.public_https import pinned_open


class Context:
    def __init__(self):
        self.hostname = None

    def wrap_socket(self, raw, server_hostname):
        self.hostname = server_hostname
        return raw


def test_pins_socket_but_retains_original_tls_hostname(monkeypatch):
    context = Context()
    connected = []

    class Connection:
        def __init__(self, host, timeout):
            self.sock = None

        def request(self, *args, **kwargs):
            pass

        def getresponse(self):
            return type(
                "R",
                (),
                {
                    "status": 200,
                    "headers": {},
                    "close": lambda s: None,
                    "read": lambda s, n=-1: b"",
                },
            )()

    monkeypatch.setattr("scraper.public_https.http.client.HTTPSConnection", Connection)
    response = pinned_open(
        Request("https://jobs.lever.co/a"),
        resolver=lambda *_a, **_k: [(None, None, None, None, ("8.8.8.8", 443))],
        connector=lambda target, timeout: connected.append(target) or object(),
        context=context,
    )
    assert connected == [("8.8.8.8", 443)]
    assert context.hostname == "jobs.lever.co"
    assert response.status == 200  # Transport returns redirects; it never follows them.


def test_mixed_dns_with_private_address_fails_closed():
    answers = [
        (None, None, None, None, ("8.8.8.8", 443)),
        (None, None, None, None, ("127.0.0.1", 443)),
    ]
    with pytest.raises(OSError):
        pinned_open(
            Request("https://jobs.lever.co/a"),
            resolver=lambda *_a, **_k: answers,
            connector=lambda *_a: pytest.fail("must not connect"),
        )
