"""Ordered service stack for ``jrc run --qa``."""

from __future__ import annotations

from typing import Sequence

from scripts.runtime_control import RuntimeContext, Service
from scripts.runtime_qa import QaRuntimeService
from scripts.runtime_qa_agent import QaAgentService
from scripts.runtime_services import (
    RequirementService,
    _livekit_forward_service,
    _mic_ui,
    _shared_services,
)


def build_qa_stack(context: RuntimeContext) -> Sequence[Service]:
    if not context.qa_mode:
        raise RuntimeError("QA stack requires --qa")
    agent = QaAgentService()
    runtime = QaRuntimeService(receipt_provider=agent.receipt_path)
    return [
        *_shared_services(context),
        _livekit_forward_service(),
        RequirementService("qa-ui", _mic_ui),
        agent,
        runtime,
    ]
