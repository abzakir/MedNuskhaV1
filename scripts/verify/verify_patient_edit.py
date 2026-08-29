"""Changing a patient's WhatsApp number, over real HTTP.

The number is the one field people genuinely get wrong, and until now the only
cure was deleting the patient - which throws away every dose, every reply and
both reports. This proves the repair works and, more importantly, that it is
safe: a new number belongs to a handset that has agreed to nothing, so the
opt-in must reset and nothing may be sent there until they answer.

Needs the backend running with DEV_AUTH_BYPASS=true.
"""
import os
import sys
from pathlib import Path

import httpx

ROOT = Path(r"C:\Users\ASUS\Desktop\MedNuskha")
sys.path.insert(0, str(ROOT / "backend"))
os.chdir(ROOT)

from sqlmodel import col, delete, select

from app.db import session_scope
from app.models import DoseEvent, Patient

BASE = "http://127.0.0.1:8000"
TAG = "ZZ-verify-edit"
OK, BAD = [], []


def check(label, cond, detail=""):
    (OK if cond else BAD).append(label)
    print(f"  {'PASS' if cond else 'FAIL'}  {label}"
          + (f"   -> {detail}" if detail and not cond else ""))


def cleanup():
    with session_scope() as s:
        for p in s.exec(select(Patient).where(col(Patient.name).contains(TAG))).all():
            s.exec(delete(DoseEvent).where(DoseEvent.patient_id == p.id))
            s.delete(p)
        s.commit()


def main() -> int:
    cleanup()
    c = httpx.Client(base_url=BASE, timeout=20)

    try:
        r = c.get("/api/health")
        if r.status_code != 200:
            print("backend not reachable - start it first")
            return 1

        # Two patients: one to edit, one to collide with.
        a = c.post("/api/patients", json={
            "name": f"{TAG} Amina", "whatsapp_number": "920000000181",
            "language": "ur"})
        b = c.post("/api/patients", json={
            "name": f"{TAG} Bushra", "whatsapp_number": "920000000182",
            "language": "ur"})
        if a.status_code != 201 or b.status_code != 201:
            print("could not create test patients:", a.status_code, a.text[:200])
            return 1
        a_id, b_id = a.json()["id"], b.json()["id"]
        print(f"created two test patients\n")

        print("=== a fresh patient starts opted in")
        before = c.get(f"/api/patients/{a_id}").json()
        check("opted_in is true to begin with", before["opted_in"] is True)

        print("\n=== renaming does NOT disturb the opt-in")
        r = c.patch(f"/api/patients/{a_id}", json={"name": f"{TAG} Amina Bibi"})
        check("rename accepted", r.status_code == 200, f"{r.status_code} {r.text[:120]}")
        body = r.json()
        check("name changed", body["name"] == f"{TAG} Amina Bibi", body["name"])
        check("still opted in", body["opted_in"] is True)
        check("no opt-in prompt for a rename", body["needs_optin"] is False)

        print("\n=== changing the number RESETS the opt-in")
        r = c.patch(f"/api/patients/{a_id}",
                    json={"whatsapp_number": "920000000183"})
        check("number change accepted", r.status_code == 200,
              f"{r.status_code} {r.text[:120]}")
        body = r.json()
        check("number is the new one", body["whatsapp_number"] == "920000000183",
              body["whatsapp_number"])
        check("THE SAFETY RULE: opt-in was reset",
              body["opted_in"] is False, str(body["opted_in"]))
        check("dashboard is told to send an intro", body["needs_optin"] is True)

        print("\n=== and the ticker will not message a patient who has not opted in")
        with session_scope() as s:
            row = s.get(Patient, a_id)
            check("opted_in is false in the database", row.opted_in is False)
            check("opted_in_at was cleared", row.opted_in_at is None)

        print("\n=== a number belonging to someone else is refused")
        r = c.patch(f"/api/patients/{a_id}",
                    json={"whatsapp_number": "920000000182"})
        check("collision refused with 409", r.status_code == 409,
              f"{r.status_code} {r.text[:120]}")
        check("and does not name the other patient",
              "Bushra" not in r.text, r.text[:120])
        after = c.get(f"/api/patients/{a_id}").json()
        check("the number was left alone",
              after["whatsapp_number"] == "920000000183",
              after["whatsapp_number"])

        print("\n=== the number is normalised, not stored as typed")
        r = c.patch(f"/api/patients/{a_id}",
                    json={"whatsapp_number": "+92 300 0000184"})
        check("spaces and + accepted", r.status_code == 200,
              f"{r.status_code} {r.text[:120]}")
        check("stored as digits only",
              r.json()["whatsapp_number"] == "923000000184",
              r.json()["whatsapp_number"])

        print("\n=== nonsense is rejected")
        r = c.patch(f"/api/patients/{a_id}", json={"whatsapp_number": "123"})
        check("too short is refused", r.status_code == 422, str(r.status_code))

        print("\n=== language can be corrected too")
        r = c.patch(f"/api/patients/{a_id}", json={"language": "en"})
        check("language changed", r.status_code == 200 and r.json()["language"] == "en",
              r.text[:120])
        r = c.patch(f"/api/patients/{a_id}", json={"language": "fr"})
        check("an unsupported language is refused", r.status_code == 422,
              str(r.status_code))

        print("\n=== another family's patient is invisible")
        r = c.patch("/api/patients/00000000-0000-0000-0000-000000000000",
                    json={"name": "nope"})
        check("unknown patient is 404", r.status_code == 404, str(r.status_code))

        print("\n=== history survives the change")
        doses = c.get(f"/api/patients/{a_id}/history?days=14").json()
        check("history endpoint still answers", "doses" in doses)

    finally:
        c.close()
        cleanup()
        print("\ncleaned up.")

    print(f"\n{'=' * 58}\n  {len(OK)} passed, {len(BAD)} failed")
    for f in BAD:
        print(f"    FAILED: {f}")
    return 1 if BAD else 0


sys.exit(main())
