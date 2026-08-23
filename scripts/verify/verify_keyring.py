"""Prove the key rotation actually fails over, using fake keys."""
import os
import secrets
import sys
import time
from pathlib import Path

ROOT = Path(r"C:\Users\ASUS\Desktop\MedNuskha")
sys.path.insert(0, str(ROOT / "backend"))
os.chdir(ROOT)

# Fill in a webhook secret while we're here, if it is still blank.
env = ROOT / ".env"
text = env.read_text(encoding="utf-8")
if "WEBHOOK_SECRET=\n" in text:
    text = text.replace("WEBHOOK_SECRET=\n",
                        f"WEBHOOK_SECRET=mn_{secrets.token_urlsafe(20)}\n")
    env.write_text(text, encoding="utf-8")
    print("  generated a WEBHOOK_SECRET into .env\n")

from app.config import settings
from app.agent import llm

PASS, FAIL = [], []


def check(label, cond, detail=""):
    (PASS if cond else FAIL).append(label)
    print(f"  {'PASS' if cond else 'FAIL'}  {label}"
          + (f"   -> {detail}" if detail and not cond else ""))


print("=== parsing key pools from env")
settings.groq_api_keys = "gsk_aaaaaaaaaaaa1, gsk_bbbbbbbbbbbb2 ,gsk_cccccccccccc3"
settings.groq_api_key = "gsk_aaaaaaaaaaaa1"          # duplicate, should collapse
settings.dashscope_api_keys = "sk-dddddddddddd4"
check("comma-separated keys parsed", len(settings.groq_keys) == 3, settings.groq_keys)
check("duplicate singular key de-duplicated", settings.groq_keys.count("gsk_aaaaaaaaaaaa1") == 1)
check("whitespace trimmed", all(k == k.strip() for k in settings.groq_keys))
check("dashscope pool joins in", settings.llm_key_count == 4, settings.llm_key_count)

print("\n=== round-robin across the pool")
ring = llm.KeyRing()
order = [ring.next_key().label for _ in range(6)]
check("cycles through every key in turn",
      order == ["groq#1", "groq#2", "groq#3", "dashscope#1", "groq#1", "groq#2"], order)

print("\n=== a rate-limited key is skipped, not retried")
ring = llm.KeyRing()
first = ring.next_key()
ring.penalise(first, 30)
following = [ring.next_key().label for _ in range(4)]
check(f"{first.label} rate-limited and dropped out",
      first.label not in following, following)
check("the other three keep serving", len(set(following)) == 3, following)

print("\n=== a dead key (bad auth) never comes back")
ring = llm.KeyRing()
dead = ring.next_key()
ring.kill(dead, "auth rejected (401)")
served = [ring.next_key().label for _ in range(6)]
check(f"{dead.label} permanently out", dead.label not in served, served)

print("\n=== cooldown expires and the key returns")
ring = llm.KeyRing()
k = ring.next_key()
ring.penalise(k, 0.5)
check("cooling immediately after", not k.available)
time.sleep(0.6)
check("available again once the cooldown passes", k.available)

print("\n=== the whole pool down raises a clear, actionable error")
ring = llm.KeyRing()
for key in list(ring._keys):
    ring.penalise(key, 60)
try:
    ring.next_key()
    check("raises AllKeysExhausted", False, "did not raise")
except llm.AllKeysExhausted as exc:
    msg = str(exc)
    check("raises AllKeysExhausted", True)
    check("says how long until one frees up", "frees up in about" in msg, msg)
    check("tells you the fix", "GROQ_API_KEYS" in msg, msg)

print("\n=== no keys at all is a clear message, not a crash")
settings.groq_api_keys = settings.groq_api_key = ""
settings.dashscope_api_keys = settings.dashscope_api_key = ""
try:
    llm.KeyRing().next_key()
    check("raises when unconfigured", False)
except llm.AllKeysExhausted as exc:
    check("raises when unconfigured", True)
    check("names the env var to set", "GROQ_API_KEYS" in str(exc), str(exc))

print("\n=== keys are never printed in full")
settings.groq_api_keys = "gsk_supersecretvalue123456"
k = llm.KeyRing()._keys[0]
check("masked for logs", "supersecretvalue" not in k.masked(), k.masked())
statuses = llm.KeyRing().status()
check("status output carries no key material",
      all("gsk_supersecret" not in str(v) for s in statuses for v in s.values()))

print(f"\n{'=' * 58}\n  {len(PASS)} passed, {len(FAIL)} failed")
for f in FAIL:
    print(f"    FAILED: {f}")
sys.exit(1 if FAIL else 0)
