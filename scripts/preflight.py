"""Check a .env is fit for a PUBLIC deployment. Standard library only.

Runs on a bare server before `docker compose up` - no virtualenv, no pip, no
imports from the app - because the point is to catch the mistakes that make a
deploy look broken before anything is built.

Every check here is something that has actually gone wrong, and each one fails
quietly rather than loudly: the site loads, the dashboard looks right, and
either no message arrives or the wrong person gets one.

    python3 scripts/preflight.py            # checks ./.env
    python3 scripts/preflight.py path/to/.env
"""

from __future__ import annotations

import sys
from pathlib import Path

OK, WARN, BAD = [], [], []


def ok(m: str) -> None:
    OK.append(m); print(f"  [OK]    {m}")


def warn(m: str) -> None:
    WARN.append(m); print(f"  [WARN]  {m}")


def bad(m: str) -> None:
    BAD.append(m); print(f"  [FAIL]  {m}")


def read_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip().upper()] = value.strip().strip('"').strip("'")
    return values


def main() -> int:
    path = Path(sys.argv[1] if len(sys.argv) > 1 else ".env")
    if not path.exists():
        print(f"No {path} - copy .env.example and fill it in.")
        return 1

    env = read_env(path)
    print(f"MedNuskha preflight - {path.resolve()}\n")

    # -- the ones that stop it working at all ------------------------------
    for name in ("DATABASE_URL", "WEBHOOK_SECRET", "SUPABASE_URL",
                 "SUPABASE_ANON_KEY"):
        if env.get(name):
            ok(f"{name} is set")
        else:
            bad(f"{name} is empty - the backend cannot run without it")

    if not (env.get("GROQ_API_KEYS") or env.get("GROQ_API_KEY")):
        bad("no Groq key - the agent cannot interpret a single reply")
    else:
        keys = [k for k in (env.get("GROQ_API_KEYS", "") + "," +
                            env.get("GROQ_API_KEY", "")).split(",") if k.strip()]
        if len(keys) == 1:
            warn("only ONE Groq key - it stops at its daily cap. Comma-separate "
                 "more to widen the pool.")
        else:
            ok(f"{len(keys)} Groq keys pooled")

    # -- the ones that fail QUIETLY, which is worse -------------------------
    api = env.get("NEXT_PUBLIC_API_BASE", "")
    if not api:
        bad("NEXT_PUBLIC_API_BASE is empty - every report link sent over "
            "WhatsApp will be dead")
    elif "localhost" in api or "127.0.0.1" in api:
        bad(f"NEXT_PUBLIC_API_BASE is still {api!r} - report links are built "
            f"from this, so every one a caretaker taps opens nothing")
    elif not api.startswith("https://"):
        bad(f"NEXT_PUBLIC_API_BASE is not HTTPS ({api!r}) - Supabase will not "
            f"redirect OAuth to plain HTTP and the browser blocks the calls")
    else:
        ok(f"NEXT_PUBLIC_API_BASE is a public HTTPS URL ({api})")

    bypass = env.get("DEV_AUTH_BYPASS", "").lower()
    if bypass in ("true", "1", "yes"):
        warn("DEV_AUTH_BYPASS is true in .env. docker-compose.yml forces it "
             "false in the container, so a compose deploy is safe - but "
             "anything running this .env directly treats every "
             "unauthenticated request as a signed-in caretaker.")
    else:
        ok("DEV_AUTH_BYPASS is off")

    if not env.get("ALLOWED_NUMBERS"):
        bad("ALLOWED_NUMBERS is empty - the bridge will send a WhatsApp "
            "message to ANY number it is handed, including a mistyped one "
            "belonging to a stranger")
    else:
        numbers = [n for n in env["ALLOWED_NUMBERS"].split(",") if n.strip()]
        ok(f"ALLOWED_NUMBERS restricts sending to {len(numbers)} number(s)")

    if not env.get("SUPABASE_SERVICE_KEY"):
        warn("SUPABASE_SERVICE_KEY is empty - reports and voice notes are not "
             "archived to Storage. Both still work; they are rebuilt on demand "
             "and re-synthesised after each deploy.")
    else:
        ok("SUPABASE_SERVICE_KEY is set - reports and voice notes are archived")

    tz = env.get("TIMEZONE", "")
    if tz and tz != "Asia/Karachi":
        warn(f"TIMEZONE is {tz!r}. Every dose time is read and written in it.")

    print(f"\n{len(OK)} ok - {len(WARN)} warning(s) - {len(BAD)} failure(s)")
    for m in BAD:
        print(f"  MUST FIX: {m}")
    for m in WARN:
        print(f"  heads up: {m}")
    return 1 if BAD else 0


sys.exit(main())
