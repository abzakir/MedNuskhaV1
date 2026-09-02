"""The conversation from the screenshot, replayed against the live system.

Observed on a real phone 2026-08-26: the agent asked "Kis ke baare mein?
Affan Jani, Zubaida Bibi", the caretaker answered "Affan jaani", and the agent
said "samajh nahi aaya" - forever. Two faults behind it:

1. `_pick` looked for the WHOLE stored name as a substring, so a first name
   alone failed and one extra letter failed.
2. Nothing remembered that a question had been asked, so a bare name - which
   is not a command - fell straight through to the unclear branch.

Outbound is captured rather than sent, so this does not message a real phone.
"""
import asyncio
import os
import sys
from pathlib import Path

# scripts/verify/<this file> -> scripts/verify -> scripts -> <repo root>
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
os.chdir(ROOT)

from sqlmodel import col, select

from app.db import session_scope
from app.models import Caretaker, Patient
from app.whatsapp import client as wa

OK, BAD = [], []
SENT = []


def check(label, cond, detail=""):
    (OK if cond else BAD).append(label)
    print(f"  {'PASS' if cond else 'FAIL'}  {label}"
          + (f"   -> {detail}" if detail and not cond else ""))


async def fake_text(to, body):
    SENT.append({"to": to, "body": body})
    return f"fake.{len(SENT)}"


wa.send_text = fake_text

from app.agent import caretaker as care

with session_scope() as s:
    row = s.exec(select(Caretaker).where(col(Caretaker.phone).isnot(None))
                 .order_by(col(Caretaker.created_at).desc())).first()
    CARE = {"id": row.id, "name": row.name, "phone": row.phone,
            "language": row.language}
    PATIENTS = [{"id": p.id, "name": p.name} for p in s.exec(
        select(Patient).where(Patient.family_id == row.family_id)).all()]

print(f"caretaker: {CARE['name']}")
print(f"patients : {[p['name'] for p in PATIENTS]}\n")

if len(PATIENTS) < 2:
    print("This check needs a caretaker with 2+ patients - that is what makes")
    print("the agent ask which one. Skipping.")
    sys.exit(0)

TARGET = PATIENTS[0]["name"]
FIRST = TARGET.split()[0]


async def send(text):
    SENT.clear()
    await care.handle(text, CARE)
    return SENT[-1]["body"] if SENT else ""


async def main() -> int:
    print("=== the name matcher, on what a human actually types")
    variants = [
        (FIRST, "first name only"),
        (FIRST.lower(), "lower case"),
        (FIRST + "  ", "trailing space"),
        (f"{FIRST} jaani", "honorific with a spelling drift"),
        (f"aur {FIRST} ka kya haal hai", "inside a sentence"),
    ]
    for typed, why in variants:
        got = care._pick(PATIENTS, typed)
        check(f"{why}: {typed.strip()!r}",
              got is not None and got["name"] == TARGET,
              got["name"] if got else "NO MATCH")

    print("\n=== it still refuses to guess when it genuinely cannot tell")
    check("gibberish matches nobody", care._pick(PATIENTS, "xyz123 qqq") is None)
    check("a name it has never seen matches nobody",
          care._pick(PATIENTS, "Ahmed Raza") is None)
    check("an empty message matches nobody", care._pick(PATIENTS, "") is None)

    print("\n=== the exact exchange from the screenshot")
    care._forget_question(CARE["id"])

    body = await send("status")
    print(f"     caretaker: status")
    print(f"     agent    : {body[:90]}")
    check("asks which patient", "?" in body and TARGET.split()[0] in body, body[:80])
    check("remembers it asked",
          care._pending_question(CARE["id"]) == "status",
          str(care._pending_question(CARE["id"])))

    body = await send(f"{FIRST} jaani")
    print(f"     caretaker: {FIRST} jaani")
    print(f"     agent    : {body[:110]}")
    check("THE BUG: the answer is understood, not refused",
          "samajh nahi aaya" not in body.lower()
          and "didn't understand" not in body.lower(), body[:90])
    check("and it answers about the right patient", TARGET in body, body[:90])
    check("the question is cleared once answered",
          care._pending_question(CARE["id"]) is None)

    print("\n=== a bare first name works too")
    care._forget_question(CARE["id"])
    await send("status")
    body = await send(FIRST)
    print(f"     caretaker: {FIRST}")
    print(f"     agent    : {body[:110]}")
    check("first name alone completes the command",
          "samajh nahi aaya" not in body.lower() and TARGET in body, body[:90])

    print("\n=== pause and resume answer the same way")
    for kind, word in (("pause", "rok dein"), ("resume", "shuru karein")):
        care._forget_question(CARE["id"])
        await send(word)
        check(f"{kind} asks which patient",
              care._pending_question(CARE["id"]) == kind,
              str(care._pending_question(CARE["id"])))
        body = await send(FIRST)
        check(f"{kind} then accepts the name",
              "samajh nahi aaya" not in body.lower(), body[:80])

    print("\n=== a name on its own, with nothing pending")
    care._forget_question(CARE["id"])
    body = await send(FIRST)
    print(f"     agent    : {body[:110]}")
    check("recognises the name rather than shrugging",
          TARGET in body and "samajh nahi aaya" not in body.lower(), body[:90])
    check("and asks what they want done",
          "status" in body.lower(), body[:90])

    print("\n=== the follow-up conversation from the second screenshot")
    care._forget_question(CARE["id"])
    care._SUBJECT.pop(CARE["id"], None)

    await send("status")
    body = await send(FIRST)
    check("status answered for the named patient", TARGET in body, body[:70])

    body = await send("Q nahi li usnay")
    print("     caretaker: Q nahi li usnay")
    print(f"     agent    : {body[:150]}")
    check("THE 2nd BUG: does not ask which patient again",
          "kis ke baare mein" not in body.lower(), body[:80])
    check("understood as a why question",
          "samajh nahi aaya" not in body.lower(), body[:80])
    check("answers about the patient we were discussing", TARGET in body, body[:80])
    check("and the answer is their own words, or says nothing was missed",
          "alfaz" in body.lower() or "own words" in body.lower()
          or "nahi chhooti" in body.lower() or "missed" in body.lower(),
          body[:110])

    print("\n=== 'why' phrased several ways all reach the same place")
    for phrasing in ["kyun nahi li", "why did he miss it", "wajah kya thi"]:
        assert care._fast_kind(phrasing) == "why", phrasing
    check("kyun / why / wajah all classify as why", True)
    check("but 'question' does not false-match on the bare q",
          care._fast_kind("question about something") != "why")

    print("\n=== a state change is never carried over silently")
    care._forget_question(CARE["id"])
    care._SUBJECT.pop(CARE["id"], None)
    await send("status")
    await send(FIRST)                      # subject is now set
    body = await send("rok dein")
    print(f"     agent    : {body[:100]}")
    check("pause still asks who, even with a subject in memory",
          "kis ke baare mein" in body.lower() or "which one" in body.lower(),
          body[:90])

    print("\n=== an emoji on its own")
    body = await send("\U0001f642")
    print(f"     agent    : {body[:110]}")
    check("does not crash, and says something", bool(body.strip()))

    print("\n=== the subject does not leak across a long gap")
    care._SUBJECT[CARE["id"]] = (PATIENTS[0]["id"], 0.0)      # expired
    check("stale subject is dropped",
          care._recent_subject(PATIENTS, CARE["id"]) is None)

    print("\n=== a stale question is not answered hours later")
    care._forget_question(CARE["id"])
    await send("status")
    care._AWAITING[CARE["id"]] = ("status", 0.0)      # expired
    check("expired question is dropped",
          care._pending_question(CARE["id"]) is None)

    print("\n=== the safety rules still hold")
    care._forget_question(CARE["id"])
    body = await send(f"should I stop {FIRST}'s medicine?")
    check("a clinical question is still refused, not read as pause",
          "doctor" in body.lower() or "faisla" in body.lower(), body[:90])
    check("and it does not leave a question pending",
          care._pending_question(CARE["id"]) is None)

    care._forget_question(CARE["id"])
    body = await send("help")
    check("help still works", "status" in body.lower(), body[:80])

    print(f"\n{'=' * 58}\n  {len(OK)} passed, {len(BAD)} failed")
    for f in BAD:
        print(f"    FAILED: {f}")
    return 1 if BAD else 0


sys.exit(asyncio.run(main()))
