# Verification scripts

Integration checks that run against the **live** Supabase database, the **live**
Groq keys and the **live** WhatsApp bridge. They are not unit tests — they are
how each phase was actually proven to work, and they are the fastest way to
find out whether something is broken right now.

Unit tests live in `backend/tests/` and run with `pytest` — no services needed.
These need the system up.

## Running them

Start everything first:

```powershell
.\dev.ps1
```

Then, from the repo root:

```powershell
backend\.venv\Scripts\python.exe scripts\verify\verify_credentials.py
```

Set `PYTHONIOENCODING=utf-8` first if Urdu output makes your console throw a
`UnicodeEncodeError` — the Windows default code page cannot print it.

## What each one proves

| Script | Checks | Needs |
|---|---|---|
| `verify_credentials.py` | Every key in `.env` actually works — Green/bridge, each Groq key individually, Whisper, Supabase | network |
| `verify_phase1.py` | Inbound parsing, webhook returns 200 fast, deduplication, message_log | database |
| `verify_inbound.py` | The bridge's exact payload shape → webhook → dose, webhook secret enforced | database |
| `verify_phase2.py` | The dose loop: taken path, missed path, late reclassification, no re-send on restart | database |
| `verify_agent.py` | Intent classification on real Urdu, dose resolution, invariant 9, emergencies | database + Groq |
| `verify_api.py` | Every REST endpoint, cross-family isolation, the confirm-before-active rule | database |
| `verify_edit_delete.py` | Changing times mid-course, stop vs delete, history never rewritten | database |
| `verify_caretaker.py` | Caretaker commands over WhatsApp, and that a clinical question is still refused | database + Groq |
| `verify_keyring.py` | API-key rotation, cooldowns, dead keys, exhaustion errors | none |
| `check_clinical.py` | The dose-change detector, including the phrasings a caretaker uses | none |

## Utilities

`purge_patient.py <number> [...]` deletes a patient and everything hanging off
them, in strict foreign-key order. Useful when a test leaves rows behind:

```powershell
backend\.venv\Scripts\python.exe scripts\verify\purge_patient.py 923001234567
```

## A warning about test data

Several of these create and delete rows in the **real** database. They clean up
after themselves, but a crashed run can leave orphans — which is what
`purge_patient.py` is for. Do not run them against a database you care about
during the demo itself.
