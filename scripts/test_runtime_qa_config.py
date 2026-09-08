import json
import subprocess

import pytest

from scripts.runtime_process import RuntimeContext
import scripts.runtime_qa_config as subject


class FakeContext(RuntimeContext):
    def __init__(self, tmp_path, responses=None):
        super().__init__(tmp_path, tmp_path / "state")
        self.responses = responses or {}
        self.commands = []

    def run(self, command, **_kwargs):
        command = tuple(command)
        self.commands.append(command)
        if command not in self.responses:
            raise AssertionError(f"unexpected command: {command}")
        return subprocess.CompletedProcess(command, *self.responses[command])


def response(stdout="", returncode=0):
    return returncode, stdout, ""


def topology(tmp_path, *, argv=None, api_peer="127.0.0.1:26443", proxy=None):
    dns = "macbook-pro.tailnet.ts.net"
    argv = argv or "kubectl port-forward -n job-radar-coach svc/livekit 7880:7880"
    proxy = proxy or "http://127.0.0.1:17880"
    serve = {
        "TCP": {"8446": {"HTTPS": True}, "7881": {"TCPForward": "127.0.0.1:17881"}},
        "Web": {
            f"{dns}:8446": {"Handlers": {"/": {"Proxy": proxy}}},
            f"{dns}:8445": {"Handlers": {"/": {"Proxy": "http://127.0.0.1:3410"}}},
        },
    }
    status = {"Self": {"DNSName": f"{dns}."}}
    return FakeContext(tmp_path, {
        ("lsof", "-nP", "-iTCP:7880", "-sTCP:LISTEN", "-t"): response("41374\n"),
        ("ps", "-ww", "-o", "command=", "-p", "41374"): response(f"{argv}\n"),
        ("lsof", "-nP", "-a", "-p", "41374", "-iTCP:7880", "-sTCP:LISTEN", "-Fn"):
            response("p41374\nn127.0.0.1:7880\nn[::1]:7880\n"),
        ("kubectl", "--context", "orbstack", "config", "view", "--minify", "-o",
         "jsonpath={.clusters[0].cluster.server}"): response("https://127.0.0.1:26443\n"),
        ("lsof", "-nP", "-a", "-p", "41374", "-iTCP", "-sTCP:ESTABLISHED", "-Fn"):
            response(f"p41374\nfn7\nn127.0.0.1:51404->{api_peer}\n"),
        ("tailscale", "serve", "status", "--json"): response(json.dumps(serve)),
        ("tailscale", "status", "--json"): response(json.dumps(status)),
    })


def test_explicit_urls_use_precedence_without_topology_reads(tmp_path):
    context = FakeContext(tmp_path)
    urls = subject.resolve_qa_urls(context, {
        "VOICE_QA_EXPECTED_LIVEKIT_URL": "ws://expected:7880",
        "LIVEKIT_URL": "ws://ignored:7880",
        "LIVEKIT_PUBLIC_URL": "wss://public.example:8446",
    })
    assert urls == subject.QaRuntimeUrls(
        expected_livekit_url="ws://expected:7880",
        public_livekit_url="wss://public.example:8446",
    )
    assert context.commands == []


def test_existing_loopback_forward_and_https_mapping_supply_defaults(tmp_path):
    context = topology(tmp_path)
    urls = subject.resolve_qa_urls(context, {})
    assert urls == subject.QaRuntimeUrls(
        expected_livekit_url="ws://127.0.0.1:7880",
        public_livekit_url="wss://macbook-pro.tailnet.ts.net:8446",
    )
    assert all(command[0:2] not in {("tailscale", "serve")}
               or command[2:] == ("status", "--json") for command in context.commands)


@pytest.mark.parametrize(
    ("argv", "code"),
    [
        ("kubectl port-forward -n job-radar-coach --address 0.0.0.0 svc/livekit 7880:7880",
         "livekit_forward_unfamiliar"),
        ("kubectl port-forward -n job-radar-coach svc/other 7880:7880",
         "livekit_forward_unfamiliar"),
    ],
)
def test_local_fallback_rejects_unsafe_or_wrong_forward(tmp_path, argv, code):
    context = topology(tmp_path, argv=argv)
    with pytest.raises(subject.QaConfigError) as caught:
        subject.resolve_qa_urls(context, {"LIVEKIT_PUBLIC_URL": "wss://public.example:8446"})
    assert caught.value.code == code


def test_implicit_forward_rejects_wrong_peer_even_if_current_context_matches(tmp_path):
    context = topology(tmp_path, api_peer="127.0.0.1:6443")
    context.responses[("kubectl", "config", "current-context")] = response("orbstack\n")
    with pytest.raises(subject.QaConfigError) as caught:
        subject.resolve_qa_urls(context, {"LIVEKIT_PUBLIC_URL": "wss://public.example:8446"})
    assert caught.value.code == "livekit_forward_wrong_peer"
    assert ("kubectl", "config", "current-context") not in context.commands


def test_public_default_rejects_conflicting_8446_mapping(tmp_path):
    context = topology(tmp_path, proxy="http://127.0.0.1:9999")
    with pytest.raises(subject.QaConfigError) as caught:
        subject.resolve_qa_urls(
            context, {"VOICE_QA_EXPECTED_LIVEKIT_URL": "ws://expected:7880"},
        )
    assert caught.value.code == "public_livekit_mapping_conflict"


def test_explicit_public_url_must_be_credential_free_wss(tmp_path):
    with pytest.raises(subject.QaConfigError) as caught:
        subject.resolve_qa_urls(FakeContext(tmp_path), {
            "VOICE_QA_EXPECTED_LIVEKIT_URL": "ws://expected:7880",
            "LIVEKIT_PUBLIC_URL": "ws://user:secret@public.example:8446",
        })
    assert caught.value.code == "invalid_public_livekit_url"
