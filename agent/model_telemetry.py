"""Request-local stage attribution for model metrics."""

from contextlib import contextmanager
from contextvars import ContextVar


UNATTRIBUTED_STAGE = "unattributed"
_MODEL_STAGE = ContextVar("model_stage", default=UNATTRIBUTED_STAGE)


@contextmanager
def model_stage(stage: str):
    token = _MODEL_STAGE.set(stage)
    try:
        yield
    finally:
        _MODEL_STAGE.reset(token)


def llm_metric_fields(metrics) -> dict[str, object]:
    return {
        "stage": _MODEL_STAGE.get(),
        "request_id": getattr(metrics, "request_id", None),
        "prompt_tokens": getattr(metrics, "prompt_tokens", None),
        "completion_tokens": getattr(metrics, "completion_tokens", None),
        "total_tokens": getattr(metrics, "total_tokens", None),
        "tokens_per_second": getattr(metrics, "tokens_per_second", None),
        "cancelled": getattr(metrics, "cancelled", None),
    }
