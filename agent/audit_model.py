"""Owned lifecycle for the independent claim-audit model."""
import logging
import os

import openai as openai_sdk
from livekit.plugins import openai as openai_plugin

DEFAULT_BASE_URL = "http://127.0.0.1:11434/v1"
DEFAULT_AUDIT_MODEL = "qwen3:4b-instruct-2507-q4_K_M"


class AuditRuntime:
    def __init__(self, model, client):
        self.model = model
        self.client = client
        self._closed = False

    async def aclose(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            await self.model.aclose()
        finally:
            await self.client.close()


async def create_auditor() -> AuditRuntime:
    base_url = (
        os.environ.get("AUDIT_LLM_BASE_URL", "").strip()
        or os.environ.get("LLM_BASE_URL", DEFAULT_BASE_URL)
    )
    model_name = os.environ.get("AUDIT_LLM_MODEL", "").strip() or DEFAULT_AUDIT_MODEL
    client = openai_sdk.AsyncClient(
        base_url=base_url,
        api_key="none",
        timeout=float(os.environ.get("LLM_TIMEOUT", "60")),
        max_retries=int(os.environ.get("LLM_HTTP_RETRIES", "0")),
    )
    try:
        model = openai_plugin.LLM(client=client, model=model_name, temperature=0)
    except BaseException:
        try:
            await client.close()
        except BaseException:
            logging.getLogger(__name__).exception(
                "audit client cleanup failed during model construction rollback"
            )
        raise
    return AuditRuntime(model, client)
