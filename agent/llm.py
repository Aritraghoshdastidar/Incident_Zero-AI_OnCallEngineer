"""Provider-agnostic chat interface. Gemini (free tier) is the default via its OpenAI-compatible
endpoint; any other OpenAI-compatible provider (Groq, OpenRouter, local Ollama) is a config change.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field

from openai import APIConnectionError, InternalServerError, NotFoundError, OpenAI, RateLimitError

from tools.config import load_dotenv

PROVIDERS = {
    "gemini": ("https://generativelanguage.googleapis.com/v1beta/openai/", "GEMINI_API_KEY", "gemini-2.5-flash"),
    "groq": ("https://api.groq.com/openai/v1", "GROQ_API_KEY", "llama-3.3-70b-versatile"),
}


# "-latest" aliases survive model retirements; the pinned lite model is a second option.
FALLBACKS = {"gemini": ["gemini-flash-lite-latest", "gemini-3.5-flash-lite"]}


@dataclass
class Usage:
    calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_s: float = 0.0


@dataclass
class LLM:
    provider: str = ""
    model: str = ""
    usage: Usage = field(default_factory=Usage)

    def __post_init__(self) -> None:
        load_dotenv()
        self.provider = self.provider or os.getenv("LLM_PROVIDER", "gemini")
        base, key_env, default_model = PROVIDERS[self.provider]
        self.model = self.model or os.getenv("LLM_MODEL", default_model)
        # Several keys per provider (KEY, KEY_2, ...) are rotated on rate limits / overload.
        keys = [os.environ[k] for k in (key_env, f"{key_env}_2", f"{key_env}_3") if os.environ.get(k)]
        self._clients = [OpenAI(base_url=base, api_key=k, max_retries=0) for k in keys]

    def chat(self, messages: list[dict], tools: list[dict] | None = None, json_mode: bool = False):
        kwargs: dict = {"model": self.model, "messages": messages, "temperature": 0.1}
        if self.provider == "gemini":
            kwargs["reasoning_effort"] = "low"  # incident triage needs speed more than long deliberation
        if tools:
            kwargs["tools"] = tools
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        # Transient provider errors (429/5xx/network) are retried with backoff; after the primary model
        # keeps failing, fall back to a lighter model so an incident is never blocked on provider load.
        resp = None
        attempt = 0
        for model in [self.model, *FALLBACKS.get(self.provider, [])]:
            kwargs["model"] = model
            for _ in range(3):
                client = self._clients[attempt % len(self._clients)]
                attempt += 1
                t0 = time.time()
                try:
                    resp = client.chat.completions.create(**kwargs)
                    break
                except NotFoundError:
                    break  # model retired/unavailable: skip straight to the next one
                except (RateLimitError, InternalServerError, APIConnectionError):
                    time.sleep(min(5 * attempt, 20))
            if resp is not None:
                break
        if resp is None:
            raise RuntimeError("LLM unavailable after retries and fallback")
        self.usage.calls += 1
        self.usage.latency_s += time.time() - t0
        if resp.usage:
            self.usage.prompt_tokens += resp.usage.prompt_tokens
            self.usage.completion_tokens += resp.usage.completion_tokens
        return resp.choices[0].message
