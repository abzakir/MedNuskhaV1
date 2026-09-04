<div align="center">

<img src="../../docs/assets/mednuskha-logo.jpg" alt="MedNuskha Icon" width="100" style="border-radius: 16px;" />

# 🧪 MedNuskha Verification Scripts

### End-to-end integration test suite & live diagnostic tools

</div>

---

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
| `verify_reports.py` | Both PDFs off a seeded 14-day course, the numbers in them, verbatim Urdu on the page, and the daily course-end job firing exactly once | database |
| `verify_report_api.py` | The two dashboard buttons and the unauthenticated WhatsApp share link, over real HTTP | database + backend running |
| `verify_voice.py` | Urdu voice notes: OGG/Opus mono, what they actually say (transcribed back), one file per unique sentence, and that the reminder path attaches rather than synthesises | database + network |
| `verify_keyring.py` | API-key rotation, cooldowns, dead keys, exhaustion errors | none |
| `check_clinical.py` | The dose-change detector, including the phrasings a caretaker uses | none |

### Two notes on the report scripts

`verify_reports.py` reads the finished PDFs back to check what is printed on
them. That needs **pypdfium2**, which is not a product dependency — fpdf2
subsets the bundled fonts, so the page content is glyph ids rather than text
and grepping the bytes finds nothing either way. Without it those particular
checks downgrade to a warning:

```powershell
backend\.venv\Scripts\python.exe -m pip install pypdfium2
```

`verify_report_api.py` talks to a **running** backend. `dev.ps1` starts uvicorn
without `--reload`, so a backend started before a code change will 404 on new
routes. Either restart it, or point the script at a second instance:

```powershell
$env:MEDNUSKHA_API = "http://127.0.0.1:8001"
```

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
