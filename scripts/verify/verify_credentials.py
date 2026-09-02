"""Verify the real credentials in .env by calling the actual services.

Never prints a secret - only masked fragments and pass/fail.
"""
import asyncio
import os
import sys
from pathlib import Path

# scripts/verify/<this file> -> scripts/verify -> scripts -> <repo root>
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
os.chdir(ROOT)

import httpx

from app.config import get_settings

get_settings.cache_clear()
from app.config import Settings

settings = Settings()

OK, BAD, WARN = [], [], []


def mask(v: str) -> str:
    if not v:
        return "(empty)"
    return f"{v[:5]}...{v[-4:]}  ({len(v)} chars)" if len(v) > 12 else "***"


def ok(m):
    OK.append(m); print(f"  [OK]    {m}")


def bad(m):
    BAD.append(m); print(f"  [FAIL]  {m}")


def warn(m):
    WARN.append(m); print(f"  [WARN]  {m}")


async def main() -> int:
    print("=" * 66)
    print("  1. WHAT IS FILLED IN")
    print("=" * 66)

    fields = [
        ("BRIDGE_URL", settings.bridge_url, True),
        ("WEBHOOK_SECRET", settings.webhook_secret, True),
        ("GROQ_API_KEYS", ",".join(settings.groq_keys), True),
        ("DATABASE_URL", settings.database_url, True),
        ("SUPABASE_URL", settings.supabase_url, True),
        ("SUPABASE_ANON_KEY", settings.supabase_anon_key, True),
        ("SUPABASE_SERVICE_KEY", settings.supabase_service_key, False),
        ("DASHSCOPE_API_KEYS", ",".join(settings.dashscope_keys), False),
    ]
    for name, value, required in fields:
        if value:
            print(f"  set     {name:<26} {mask(value)}")
        elif required:
            bad(f"{name} is EMPTY")
        else:
            print(f"  blank   {name:<26} (optional - fine for now)")

    print(f"\n  LLM key pool: {settings.llm_key_count} key(s) "
          f"- {len(settings.groq_keys)} groq, {len(settings.dashscope_keys)} dashscope")
    if len(settings.groq_keys) == 1:
        warn("only ONE Groq key - if it hits its daily cap the agent stops. "
             "Add teammates' keys, comma-separated.")
    elif len(settings.groq_keys) > 1:
        ok(f"{len(settings.groq_keys)} Groq keys pooled - rotation has headroom")

    # ------------------------------------------------------------------
    print("\n" + "=" * 66)
    print("  2. WHATSAPP BRIDGE - is WhatsApp actually connected?")
    print("=" * 66)

    # Green API was replaced by the local Baileys bridge on 2026-08-22
    # (PROJECT_LOG.md). The question is the same one - can we send? - but the
    # answer now comes from a process on this machine rather than a vendor.
    async with httpx.AsyncClient(timeout=10.0) as c:
        try:
            r = await c.get(f"{settings.bridge_url.rstrip('/')}/status")
        except httpx.HTTPError as exc:
            bad(f"bridge unreachable at {settings.bridge_url} ({exc}) - "
                f"start it with `make bridge`")
        else:
            if r.status_code >= 300:
                bad(f"bridge returned {r.status_code}: {r.text[:200]}")
            else:
                status = r.json()
                state = status.get("state")
                print(f"  state = {state!r}   number = {status.get('me') or '-'}")
                if state == "connected":
                    ok(f"WhatsApp connected as {status.get('me')} - it can send")
                elif state == "qr":
                    bad("bridge is waiting to be PAIRED - scan the QR code "
                        "printed in its terminal from the spare phone")
                elif state == "logged_out":
                    bad("this device was unlinked. Delete "
                        "whatsapp-bridge/auth_info/ and pair again.")
                else:
                    warn(f"bridge is {state!r} - it reconnects on its own; "
                         f"re-run this in a moment")

                allowlist = status.get("allowlist") or []
                if allowlist:
                    ok(f"ALLOWED_NUMBERS is set ({len(allowlist)} number(s)) - "
                       f"a mis-typed number cannot reach a stranger")
                else:
                    warn("ALLOWED_NUMBERS is empty - the bridge will message "
                         "ANY number it is given. Set it on any deployed host.")

    if not settings.webhook_secret:
        bad("WEBHOOK_SECRET is empty - the webhook is then open to anyone who "
            "guesses the URL, and could be posted a fake dose confirmation")

    if settings.dev_auth_bypass:
        warn("DEV_AUTH_BYPASS is true - every unauthenticated request is "
             "treated as a caretaker. Fine locally, never in production.")

    # ------------------------------------------------------------------
    print("\n" + "=" * 66)
    print("  3. GROQ - does each key actually work?")
    print("=" * 66)

    if not settings.groq_keys:
        bad("no Groq keys configured")
    else:
        async with httpx.AsyncClient(timeout=45.0) as c:
            for i, key in enumerate(settings.groq_keys, 1):
                label = f"groq#{i}"
                try:
                    r = await c.post(
                        "https://api.groq.com/openai/v1/chat/completions",
                        headers={"Authorization": f"Bearer {key}",
                                 "Content-Type": "application/json"},
                        # GROQ_REASONING_EFFORT exactly as the agent sends it.
                        # Without it this model prefixes every reply with a
                        # <think> block, and a check that passes on output the
                        # app would never see is not a check.
                        json={"model": settings.groq_model,
                              "messages": [{"role": "user",
                                            "content": "Reply with the single word: ok"}],
                              "max_tokens": 5, "temperature": 0,
                              **({"reasoning_effort": settings.groq_reasoning_effort}
                                 if settings.groq_reasoning_effort else {})},
                    )
                except httpx.HTTPError as exc:
                    bad(f"{label} {mask(key)} - network error: {exc}")
                    continue

                if r.status_code == 200:
                    reply = r.json()["choices"][0]["message"]["content"].strip()
                    ok(f"{label} {mask(key)} - working (model replied {reply!r})")
                elif r.status_code == 401:
                    bad(f"{label} {mask(key)} - INVALID KEY (401)")
                elif r.status_code == 429:
                    warn(f"{label} {mask(key)} - valid but rate-limited right now")
                elif r.status_code == 404:
                    bad(f"{label} - model {settings.groq_model!r} not found. "
                        f"Check GROQ_MODEL against console.groq.com/docs/models")
                else:
                    bad(f"{label} {mask(key)} - {r.status_code}: {r.text[:200]}")

    # ------------------------------------------------------------------
    print("\n" + "=" * 66)
    print("  4. GROQ WHISPER - can it transcribe Urdu?")
    print("=" * 66)

    sample = Path(__file__).with_name("asr_taken.mp3")
    if not sample.exists():
        warn("no sample audio to test with - skipping")
    elif not settings.groq_keys:
        bad("no Groq key to test transcription with")
    else:
        async with httpx.AsyncClient(timeout=60.0) as c:
            r = await c.post(
                "https://api.groq.com/openai/v1/audio/transcriptions",
                headers={"Authorization": f"Bearer {settings.groq_keys[0]}"},
                files={"file": ("voice.mp3", sample.read_bytes(), "audio/mpeg")},
                data={"model": settings.groq_whisper_model, "language": "ur",
                      "response_format": "text"},
            )
        if r.status_code == 200:
            heard = r.text.strip()
            ok(f"whisper-large-v3 works - heard: {heard!r}")
            print("     (the audio says 'le li hai' - 'I have taken it')")
        elif r.status_code == 404:
            bad(f"model {settings.groq_whisper_model!r} not available on this key")
        else:
            bad(f"transcription failed {r.status_code}: {r.text[:200]}")

    # ------------------------------------------------------------------
    print("\n" + "=" * 66)
    print("  5. DATABASE")
    print("=" * 66)
    try:
        from sqlalchemy import text
        from app.db import get_engine
        with get_engine().connect() as conn:
            n = conn.execute(text(
                "select count(*) from information_schema.tables "
                "where table_schema='public'")).scalar()
        ok(f"Supabase reachable - {n} tables")
    except Exception as exc:  # noqa: BLE001
        bad(f"database unreachable: {str(exc)[:200]}")

    print("\n" + "=" * 66)
    print(f"  {len(OK)} ok · {len(WARN)} warnings · {len(BAD)} failures")
    print("=" * 66)
    for m in BAD:
        print(f"  MUST FIX: {m}")
    for m in WARN:
        print(f"  heads up: {m}")
    return 1 if BAD else 0


sys.exit(asyncio.run(main()))
