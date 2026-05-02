"""LLM clients: Grok primary + Opus validator, plus mock variants.

Both clients return a `LLMResponse(text, model)`. JSON parsing is best-effort
via `parse_json_or_empty` — never raises, returns `{}` on bad input. The
calling code already treats empty as a soft failure.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any

import httpx
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from app.config import Settings

log = logging.getLogger(__name__)


@dataclass
class LLMResponse:
    text: str
    model: str


# ---------------------------------------------------------------------------
# Grok (xAI) — OpenAI-compatible chat completions
# ---------------------------------------------------------------------------
class GrokClient:
    def __init__(self, settings: Settings):
        self.s = settings
        self.base_url = settings.grok_base_url.rstrip("/")
        self.model = settings.grok_model

    def chat(self, system: str, user: str, *, response_format_json: bool = False,
             max_tokens: int = 4000) -> LLMResponse:
        if self.s.mock_data or not self.s.xai_api_key:
            return _mock_grok_response(system, user)
        return self._chat_with_retry(system, user, response_format_json, max_tokens)

    @retry(
        retry=retry_if_exception(lambda e: isinstance(e, _RetryableError)),
        wait=wait_exponential(multiplier=2, min=2, max=20),
        stop=stop_after_attempt(4),
        reraise=True,
    )
    def _chat_with_retry(self, system: str, user: str,
                         response_format_json: bool, max_tokens: int) -> LLMResponse:
        headers = {
            "Authorization": f"Bearer {self.s.xai_api_key}",
            "Content-Type": "application/json",
        }
        body: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "max_tokens": max_tokens,
            "temperature": 0.2,
        }
        if response_format_json:
            body["response_format"] = {"type": "json_object"}
        if self.s.grok_thinking:
            body["reasoning"] = {"effort": "high"}

        with httpx.Client(timeout=120.0) as client:
            r = client.post(f"{self.base_url}/chat/completions", headers=headers, json=body)
            if 500 <= r.status_code < 600 or r.status_code == 429:
                # Transient: retry with backoff.
                raise _RetryableError(
                    f"xAI {r.status_code} for model={self.model}: {r.text[:500]}"
                )
            if r.status_code >= 400:
                # Permanent: don't waste retries on 4xx (auth/model/etc).
                raise RuntimeError(
                    f"xAI {r.status_code} for model={self.model}: {r.text[:1000]}"
                )
            data = r.json()

        text = (data.get("choices") or [{}])[0].get("message", {}).get("content", "") or ""
        return LLMResponse(text=text, model=data.get("model", self.model))


class _RetryableError(Exception):
    """xAI returned 5xx or 429 — try again with backoff."""


# ---------------------------------------------------------------------------
# Opus validator (Anthropic SDK)
# ---------------------------------------------------------------------------
class OpusValidator:
    def __init__(self, settings: Settings):
        self.s = settings
        self.model = settings.anthropic_model

    def critique(self, system: str, user: str) -> LLMResponse:
        if self.s.mock_data or not self.s.anthropic_api_key:
            return _mock_opus_response(system, user)

        # Imported lazily so mock-mode users don't need anthropic installed at runtime.
        from anthropic import Anthropic

        client = Anthropic(api_key=self.s.anthropic_api_key)
        # Opus 4.7 API shape:
        #   - `temperature` / `top_p` / `top_k` removed (400 if sent)
        #   - `thinking={"type": "enabled", "budget_tokens": N}` removed
        #   - Use `thinking={"type": "adaptive"}` + `output_config={"effort": ...}`
        #     where effort ∈ low | medium | high | xhigh | max
        kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": 4000,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }
        if self.s.extended_thinking:
            kwargs["thinking"] = {"type": "adaptive"}
            kwargs["output_config"] = {"effort": "high"}

        msg = client.messages.create(**kwargs)
        # Pull the first text block; thinking blocks are skipped.
        text_parts = [b.text for b in msg.content if getattr(b, "type", None) == "text"]
        return LLMResponse(text="".join(text_parts), model=msg.model)


# ---------------------------------------------------------------------------
# Mocks — deterministic responses for MOCK_DATA mode and tests.
# ---------------------------------------------------------------------------
def _mock_grok_response(system: str, user: str) -> LLMResponse:
    # The causal engine has its own _mock_causal_output() short-circuit and
    # never calls into here in MOCK_DATA mode. Returning empty JSON keeps
    # parse_json_or_empty happy if any other caller hits us.
    return LLMResponse(text="{}", model="grok-mock")


def _mock_opus_response(system: str, user: str) -> LLMResponse:
    verdict = {
        "decision": "accept",
        "news_check": "Headlines align with fixture corpus.",
        "trade_theory_check": "Causal chain is internally consistent.",
        "risk_reward_check": "Spread/YOLO math sane.",
        "option_strategy_check": "Structure matches thesis.",
        "issues": [],
        "revisions_suggested": [],
        "confidence": 0.78,
    }
    return LLMResponse(text=json.dumps(verdict), model="opus-mock")


# ---------------------------------------------------------------------------
# Robust JSON extraction. LLMs sometimes wrap JSON in ``` fences or prose.
# ---------------------------------------------------------------------------
_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


def parse_json_or_empty(text: str) -> dict:
    if not text:
        return {}
    candidates: list[str] = [text]
    for m in _FENCE_RE.finditer(text):
        candidates.append(m.group(1))
    # Last resort: pluck the substring between the first { and last }.
    if "{" in text and "}" in text:
        candidates.append(text[text.index("{") : text.rindex("}") + 1])
    for c in candidates:
        try:
            obj = json.loads(c)
            if isinstance(obj, dict):
                return obj
        except (json.JSONDecodeError, ValueError):
            continue
    return {}
