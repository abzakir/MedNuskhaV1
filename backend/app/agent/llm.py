"""Shared LLM client with automatic API-key rotation.

Every free tier has a daily cap. One key running out at 11pm the night before
the demo would take the agent down, so keys are pooled: several Groq keys, plus
Alibaba Model Studio keys when the hackathon credits arrive. A key that returns
429 is put on a short cooldown and the next one takes over. Nothing stops until
every key in the pool is exhausted at once.

Both providers speak the OpenAI chat-completions dialect, so the same request
body works for either. That is also what makes the eventual move from Groq to
Alibaba a config change rather than a rewrite.

Not in the AGENTS.md section 7 layout - added 2026-08-22 so interpret.py,
respond.py and knowledge.py share one client instead of three copies. Logged in
PROJECT_LOG.md.
"""

from __future__ import annotations

import itertools
import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.config import settings

log = logging.getLogger(__name__)

GROQ_BASE = "https://api.groq.com/openai/v1"

#: Reasoning models wrap their scratchpad in <think>...</think>. We suppress it
#: at request time, but strip it here too - a stray thinking block reaching a
#: 68-year-old, or a JSON parser, is not a failure mode worth risking on one
#: layer of defence.
_THINK = re.compile(r"<think>.*?</think>\s*", re.DOTALL | re.IGNORECASE)
DASHSCOPE_BASE = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"


class AllKeysExhausted(RuntimeError):
    """Every key in the pool is rate-limited or dead at the same moment."""


class LLMError(RuntimeError):
    """A non-retryable failure from the provider."""


@dataclass
class PooledKey:
    provider: str
    key: str
    label: str
    base_url: str
    model: str
    cooldown_until: float = 0.0
    calls: int = 0
    failures: int = 0
    dead: bool = False

    @property
    def available(self) -> bool:
        return not self.dead and time.time() >= self.cooldown_until

    @property
    def cooling_for(self) -> int:
        return max(0, int(self.cooldown_until - time.time()))

    def masked(self) -> str:
        """Never log a whole key."""
        return f"{self.key[:6]}...{self.key[-4:]}" if len(self.key) > 12 else "***"


class KeyRing:
    """Round-robins a pool of keys, skipping any that are cooling down."""

    def __init__(self) -> None:
        self._keys: list[PooledKey] = []
        self._cycle: itertools.cycle | None = None
        self.reload()

    def reload(self) -> None:
        keys: list[PooledKey] = []
        for i, key in enumerate(settings.groq_keys, 1):
            keys.append(PooledKey("groq", key, f"groq#{i}",
                                  GROQ_BASE, settings.groq_model))
        for i, key in enumerate(settings.dashscope_keys, 1):
            keys.append(PooledKey("dashscope", key, f"dashscope#{i}",
                                  DASHSCOPE_BASE, settings.dashscope_model))
        self._keys = keys
        self._index = 0
        if keys:
            log.info("LLM key pool: %s", ", ".join(k.label for k in keys))

    def __len__(self) -> int:
        return len(self._keys)

    def next_key(self) -> PooledKey:
        """The next usable key, round-robin. Raises when all are unavailable."""
        if not self._keys:
            raise AllKeysExhausted(
                "No LLM keys configured. Set GROQ_API_KEYS in .env "
                "(comma-separated - more keys means more headroom)."
            )

        n = len(self._keys)
        for offset in range(n):
            candidate = self._keys[(self._index + offset) % n]
            if candidate.available:
                self._index = (self._index + offset + 1) % n
                return candidate

        soonest = min(k.cooling_for for k in self._keys if not k.dead) \
            if any(not k.dead for k in self._keys) else 0
        raise AllKeysExhausted(
            f"All {n} LLM keys are rate-limited or dead. "
            f"Next one frees up in about {soonest}s. Add another key to "
            f"GROQ_API_KEYS to widen the pool."
        )

    def penalise(self, key: PooledKey, seconds: float | None = None) -> None:
        wait = seconds if seconds is not None else settings.llm_cooldown_seconds
        key.cooldown_until = time.time() + wait
        key.failures += 1
        log.warning("key %s rate-limited, resting %.0fs (%d of %d keys still up)",
                    key.label, wait, sum(1 for k in self._keys if k.available),
                    len(self._keys))

    def kill(self, key: PooledKey, reason: str) -> None:
        key.dead = True
        log.error("key %s (%s) disabled: %s", key.label, key.masked(), reason)

    def status(self) -> list[dict[str, Any]]:
        """For /api/health - never includes the key itself."""
        return [{
            "label": k.label,
            "provider": k.provider,
            "model": k.model,
            "state": "dead" if k.dead else ("cooling" if not k.available else "ready"),
            "cooling_for": k.cooling_for,
            "calls": k.calls,
            "failures": k.failures,
        } for k in self._keys]


_ring: KeyRing | None = None


def ring() -> KeyRing:
    global _ring
    if _ring is None:
        _ring = KeyRing()
    return _ring


def strip_reasoning(text: str) -> str:
    """Remove any <think> block a reasoning model emitted."""
    cleaned = _THINK.sub("", text or "").strip()
    # An unterminated block means the reply was cut off mid-thought; there is
    # no usable answer in it.
    if "<think>" in cleaned.lower():
        cleaned = cleaned[:cleaned.lower().index("<think>")].strip()
    return cleaned


def _retry_after(response: httpx.Response) -> float | None:
    raw = response.headers.get("retry-after")
    if raw:
        try:
            return float(raw)
        except ValueError:
            pass
    return None


async def chat(
    messages: list[dict[str, str]],
    *,
    temperature: float = 0.2,
    max_tokens: int = 512,
    json_mode: bool = False,
    timeout: float = 30.0,
) -> str:
    """Send a chat completion, rotating keys past any that are rate-limited.

    Returns the assistant's message content. Raises AllKeysExhausted only when
    every key in the pool is unavailable at the same time.
    """
    keyring = ring()
    attempts = max(len(keyring), 1)
    last_error: Exception | None = None

    async with httpx.AsyncClient(timeout=timeout) as client:
        for _ in range(attempts):
            key = keyring.next_key()          # raises if the whole pool is down
            body: dict[str, Any] = {
                "model": key.model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
            if json_mode:
                body["response_format"] = {"type": "json_object"}
            if key.provider == "groq" and settings.groq_reasoning_effort:
                body["reasoning_effort"] = settings.groq_reasoning_effort

            try:
                resp = await client.post(
                    f"{key.base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {key.key}",
                             "Content-Type": "application/json"},
                    json=body,
                )
            except httpx.HTTPError as exc:
                last_error = exc
                keyring.penalise(key, 10)      # network blip: brief rest
                continue

            key.calls += 1

            if resp.status_code == 429:
                keyring.penalise(key, _retry_after(resp))
                last_error = LLMError(f"{key.label} rate-limited")
                continue

            if resp.status_code in (401, 403):
                keyring.kill(key, f"auth rejected ({resp.status_code})")
                last_error = LLMError(f"{key.label} auth failed")
                continue

            if resp.status_code >= 500:
                keyring.penalise(key, 15)
                last_error = LLMError(f"{key.label} server error {resp.status_code}")
                continue

            if resp.status_code >= 400:
                # A bad request is our fault - another key will fail identically.
                raise LLMError(f"{key.label}: {resp.status_code} {resp.text[:300]}")

            data = resp.json()
            try:
                return strip_reasoning(data["choices"][0]["message"]["content"])
            except (KeyError, IndexError) as exc:
                raise LLMError(f"unexpected response shape: {data}") from exc

    raise AllKeysExhausted(
        f"every key failed in turn ({attempts} attempts). Last error: {last_error}"
    )


async def chat_json(
    messages: list[dict[str, str]],
    *,
    temperature: float = 0.0,
    max_tokens: int = 512,
) -> dict:
    """chat() constrained to JSON, parsed.

    Models sometimes wrap JSON in prose or a code fence even in JSON mode, so
    the outermost braces are extracted before parsing rather than trusting the
    response to be clean.
    """
    raw = await chat(messages, temperature=temperature,
                     max_tokens=max_tokens, json_mode=True)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        start, end = raw.find("{"), raw.rfind("}")
        if start != -1 and end > start:
            try:
                return json.loads(raw[start:end + 1])
            except json.JSONDecodeError:
                pass
        raise LLMError(f"model did not return JSON: {raw[:300]}")


async def transcribe(audio: bytes, filename: str = "voice.ogg",
                     language: str = "ur") -> str:
    """Transcribe audio with Groq's whisper-large-v3, rotating keys.

    Far more accurate on Urdu than the local model - see PROJECT_LOG.md, where
    the local `base` model was measured inverting "abhi nahi" into "ab hi".
    Raises AllKeysExhausted if the whole pool is down, and voice/asr.py then
    falls back to the local model.
    """
    keyring = ring()
    groq_keys = [k for k in keyring._keys if k.provider == "groq"]
    if not groq_keys:
        raise AllKeysExhausted("no Groq key configured for transcription")

    last_error: Exception | None = None
    async with httpx.AsyncClient(timeout=60.0) as client:
        for key in groq_keys:
            if not key.available:
                continue
            try:
                resp = await client.post(
                    f"{GROQ_BASE}/audio/transcriptions",
                    headers={"Authorization": f"Bearer {key.key}"},
                    files={"file": (filename, audio, "audio/ogg")},
                    data={"model": settings.groq_whisper_model,
                          "language": language,
                          "response_format": "text"},
                )
            except httpx.HTTPError as exc:
                last_error = exc
                keyring.penalise(key, 10)
                continue

            key.calls += 1
            if resp.status_code == 429:
                keyring.penalise(key, _retry_after(resp))
                last_error = LLMError(f"{key.label} rate-limited")
                continue
            if resp.status_code in (401, 403):
                keyring.kill(key, f"auth rejected ({resp.status_code})")
                continue
            if resp.status_code >= 300:
                last_error = LLMError(f"{key.label}: {resp.status_code} "
                                      f"{resp.text[:200]}")
                continue

            return resp.text.strip()

    raise AllKeysExhausted(f"no Groq key could transcribe. Last error: {last_error}")
