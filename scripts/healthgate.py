"""Read /api/health from stdin and decide whether a deploy succeeded.

A FILE, not a `python3 -c` string inside deploy.sh. That is not fussiness:
the inline version was written twice and broke twice, both times on shell
quoting rather than on anything to do with health.

  - escaped double quotes did not survive the heredoc, python read the
    backslash as a line continuation, and the block died with SyntaxError
  - single quotes then ended the shell's own single-quoted argument, so
    python received `d[status]` and died with NameError

Both failed the same way: the gate crashes, the retry loop burns every
attempt, and a perfectly healthy deploy reports FAILED - while a genuinely
broken one looks identical. A file has no quoting layer to get wrong.

    curl -fsS localhost:8000/api/health | python3 scripts/healthgate.py

Exit 0 healthy, 2 degraded, 1 unreadable.
"""

from __future__ import annotations

import json
import sys


def main() -> int:
    try:
        d = json.load(sys.stdin)
    except Exception as exc:  # noqa: BLE001
        print(f"  could not read /api/health: {exc}")
        return 1

    whatsapp = (d.get("whatsapp") or {}).get("state")
    lock = d.get("scheduler_lock")
    llm = d.get("llm") or {}

    print(f"  status     {d.get('status')}")
    print(f"  database   {d.get('database')}")
    print(f"  scheduler  {d.get('scheduler')}  (lock: {lock})")
    print(f"  whatsapp   {whatsapp}")
    print(f"  llm        {llm.get('ready')}/{llm.get('total')} keys")

    bad = []
    if d.get("status") != "ok":
        bad.append("status")
    if d.get("database") != "connected":
        bad.append("database")
    if whatsapp != "connected":
        bad.append("whatsapp")
    # "not held" means another process is sending, which is a real answer but
    # not one a deploy should report as success.
    if lock != "held":
        bad.append("scheduler_lock")
    if not llm.get("ready"):
        bad.append("llm")

    if bad:
        print("  DEGRADED: " + ", ".join(bad))
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
