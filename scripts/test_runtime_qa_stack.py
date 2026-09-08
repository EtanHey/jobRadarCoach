import subprocess

from scripts.runtime_control import Probe, RuntimeContext, Supervisor
import scripts.runtime_qa_stack as subject


class Context(RuntimeContext):
    def __init__(self, tmp_path, http_status="404"):
        super().__init__(tmp_path, tmp_path / "state", qa_mode=True)
        self.http_status = http_status

    def run(self, command, **_kwargs):
        if command[0] == "curl":
            return subprocess.CompletedProcess(command, 0, self.http_status, "")
        raise AssertionError(f"unexpected command: {command}")


class Sentinel:
    def __init__(self, name):
        self.name = name
        self.probes = self.starts = 0

    def probe(self, _context):
        self.probes += 1
        return Probe(True, "fixture")

    def start(self, _context):
        self.starts += 1
        return {}


class Agent(Sentinel):
    def __init__(self):
        super().__init__("qa-agent")

    def receipt_path(self, context):
        return context.state_dir / "qa-agent-receipt.json"


class Runtime(Sentinel):
    def __init__(self, receipt_provider):
        super().__init__("qa-runtime")
        self.receipt_provider = receipt_provider


def stack(monkeypatch, normal):
    monkeypatch.setattr(subject, "_shared_services", lambda _context: normal)
    monkeypatch.setattr(subject, "_livekit_forward_service", lambda: Sentinel("livekit-forward"))
    monkeypatch.setattr(subject, "QaAgentService", Agent)
    monkeypatch.setattr(subject, "QaRuntimeService", Runtime)


def test_qa_order_excludes_normal_agent_and_binds_owned_receipt(monkeypatch, tmp_path):
    normal = [Sentinel("kubernetes"), Sentinel("ui")]
    stack(monkeypatch, normal)
    services = subject.build_qa_stack(Context(tmp_path, "200"))
    assert [service.name for service in services] == [
        "kubernetes", "ui", "livekit-forward", "qa-ui", "qa-agent", "qa-runtime",
    ]
    agent, runtime = services[-2:]
    assert runtime.receipt_provider.__self__ is agent
    assert runtime.receipt_provider(Context(tmp_path)) == agent.receipt_path(Context(tmp_path))
    assert all(service.name != "room-agent" for service in services)


def test_mic_404_refuses_after_forwards_and_before_agent(monkeypatch, tmp_path):
    earlier = Sentinel("ui-forward")
    stack(monkeypatch, [earlier])
    supervisor = Supervisor(Context(tmp_path), subject.build_qa_stack(Context(tmp_path)))
    assert supervisor.up() == 1
    assert earlier.probes == 1 and earlier.starts == 0
    services = supervisor.services
    assert services[1].probes == 1
    assert services[-2].probes == 0 and services[-2].starts == 0


def test_mic_probe_requires_exact_200(tmp_path):
    assert subject._mic_ui(Context(tmp_path, "200")).healthy
    assert not subject._mic_ui(Context(tmp_path, "302")).healthy


def test_direct_stack_call_requires_qa_mode(tmp_path):
    context = RuntimeContext(tmp_path, tmp_path / "state")
    try:
        subject.build_qa_stack(context)
    except RuntimeError as error:
        assert "requires --qa" in str(error)
    else:
        raise AssertionError("normal context entered QA stack")
