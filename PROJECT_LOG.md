# MedNuskha — Project Log

## Current state

**Phase 0 is complete and the gate passes.** Verified this session, not assumed:

- `backend/.venv` built on **Python 3.14.4**; all of `requirements.txt` installed.
- Backend boots. `GET /api/health` returns **200** with an honest body reporting
  which env vars are missing.
- Frontend `npm run build` compiles clean with types checked; `npm run dev`
  serves on :3000.
- Both run together, and the dashboard **successfully fetches the backend
  across origins** (CORS confirmed working in a real browser, not just curl).
- `pytest` runs green: 2 skipped, 0 failed.

**What is real code:** `config.py`, `db.py`, `models.py` (all 11 tables),
`main.py`, `frontend/lib/api.ts`, `frontend/app/page.tsx`.

**What is a stub:** every other backend module. Each has its frozen §9
signature, a docstring explaining what it must do and which invariants apply,
and a body that `raise NotImplementedError("Phase N — …")`. Nothing silently
returns a wrong answer or `pass`es. The two test files skip at module level
with the phase named, so `make test` is green rather than red-by-default — the
adversarial case lists are already written out in them as data.

**What is broken / not yet possible:**

- **No database.** `DATABASE_URL` is empty, so no Supabase project exists yet
  and no table has actually been created. `init_db()` is wired and will run on
  the next boot once the URL is set. Health reports `"database": "not connected"`.
- **No WhatsApp.** No Meta app, no token, no templates submitted.
- **WeasyPrint installs but does not import on Windows** — needs the GTK
  runtime. Blocks Phase 6 on a Windows dev machine. See Gotchas.
- `make seed` exits 1 with a clear message; it lands in Phase 8.

## Current phase

**Phase 0 — Bootstrap: done.** Nothing remains on Claude's side.

The blocker is now entirely on the human side, and it is time-sensitive:
**the four WhatsApp templates must be submitted today.** Approval takes hours
and sometimes a day, and Phase 1 cannot be verified without `dose_reminder`.

## Next steps

Ordered. Steps 1–3 are the humans' Phase 0 "Your turn"; they gate everything.

1. **Submit the four WhatsApp templates first — before anything else.**
   Meta Developer app → Business → add the WhatsApp product. In
   WhatsApp Manager → Message Templates, submit all four from AGENTS.md §10
   (`dose_reminder`, `dose_followup`, `caretaker_alert`, `patient_optin`), all
   category UTILITY. Nothing else today matters more.
2. Still in the Meta app: save `WHATSAPP_PHONE_NUMBER_ID` and
   `WHATSAPP_WABA_ID`. In WhatsApp → API Setup, whitelist three team numbers on
   the free test number and enter each confirmation code.
3. Meta Business Settings → create a **System User**, assign the WABA asset,
   generate a **permanent token** with `whatsapp_business_messaging` and
   `whatsapp_business_management`. Save as `WHATSAPP_TOKEN` (this replaces the
   24-hour temp token). Invent a random string for `WHATSAPP_VERIFY_TOKEN`.
4. Create the Supabase project (free tier). Copy `DATABASE_URL`, `SUPABASE_URL`,
   `SUPABASE_ANON_KEY`. Create a **private** `voice-notes` storage bucket.
5. Create a DashScope account (dashscope.aliyun.com), redeem the hackathon
   credit code, save `DASHSCOPE_API_KEY`.
6. `cp .env.example .env` and fill it in.
7. Run `.\dev.ps1`, open http://localhost:3000, and confirm the card now reads
   **database: connected**. That is the proof the schema actually created — the
   11 tables appear in Supabase on that first boot.
8. Then start Phase 1 (WhatsApp transport) with the master prompt from §0 plus
   the Phase 1 prompt from §14.

## Environment / setup

**Toolchain on the current dev machine (Windows 11):** Python 3.14.4,
Node 24.18.0, npm 11.16.0, git 2.54.0. **`make` is not installed.**

**Commands** — the Makefile is canonical and is what runs on the ECS box in
Phase 8. On Windows use the PowerShell shims, which do the same thing:

| Purpose | Makefile | Windows |
|---|---|---|
| install deps | `make install` | `.\install.ps1` |
| run both processes | `make dev` | `.\dev.ps1` |
| tests | `make test` | `.\test.ps1` |
| seed demo data | `make seed` | `.\seed.ps1` |

Backend on :8000 (health at `/api/health`), frontend on :3000.

**Env vars** — names only, in `.env.example`. `.env` is gitignored. All five of
`DATABASE_URL`, `WHATSAPP_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID`,
`WHATSAPP_VERIFY_TOKEN`, `DASHSCOPE_API_KEY` are currently **unset**;
`/api/health` lists exactly which are missing at any time.

**Accounts still to create:** Meta Developer + WABA, Supabase, DashScope,
Google Cloud (TTS — not needed until Phase 5).

**Git / GitHub:** remote is `https://github.com/abzakir/MedNuskha`, branch
`main`. Phase 0 is pushed (`a163ac9`). **Standing instruction from the team:
commit and push at the end of every phase** — one commit per phase, message in
the `feat(scope): ...` form from §12. `.gitattributes` normalises the repo to
LF (with `.ps1` kept CRLF) because the backend ships to an Ubuntu ECS box in
Phase 8, where a CRLF Makefile breaks.

**WhatsApp templates:** none submitted yet. All four are pending action.

## Gotchas discovered

- **WeasyPrint installs on Windows but will not import.** `import weasyprint`
  raises `OSError: cannot load library 'libgobject-2.0-0'` — it needs the GTK3
  runtime, which pip does not provide. **This blocks Phase 6 on Windows.** Two
  ways out: install the GTK3 Runtime for Windows on the dev machine, or accept
  that PDFs only generate on the Ubuntu ECS box (Phase 8), where `apt` pulls
  Pango in as a normal dependency. Decide before Phase 6 starts, not during it.
  Nothing imports weasyprint yet, so this is inert until then.
- **Everything else installs and imports cleanly on Python 3.14**, including the
  two that were most at risk: `faster-whisper 1.2.1` (with `ctranslate2 4.8.1`
  cp314 wheels) and `google-cloud-texttospeech 2.37.0`. The Day-3 wheel risk is
  effectively gone.
- **`shadcn init -d` fails** with `Validation failed: - tailwind: Required`.
  `shadcn@2 init -d -b zinc` works — the base colour must be passed explicitly.
  Without `-d` the CLI prompts interactively and hangs in a non-TTY.
- **`create-next-app` initialises its own git repo inside `frontend/`.** It was
  deleted so the project has one repo at the root, not a nested one. If anyone
  re-scaffolds the frontend, delete `frontend/.git` again.
- **Git Bash heredocs on this machine collapse `\\` to `\`.** A Python docstring
  written that way produces a `SyntaxWarning: invalid escape sequence`. Use the
  Write tool, or avoid backslashes, for Python files.
- **Supabase's transaction-mode pooler (port 6543) cannot use server-side
  prepared statements.** `db.py` already passes `prepare_threshold: None` and
  `pool_pre_ping=True` (free-tier projects pause after inactivity and drop idle
  connections). Do not remove either.
- **Supabase hands out `postgresql://` URLs**, which SQLAlchemy maps to psycopg2
  — a driver we do not install. `settings.sqlalchemy_url` rewrites the scheme to
  `postgresql+psycopg://`. Always use `settings.sqlalchemy_url`, never
  `settings.database_url`, to build an engine.

## Decisions log

### 2026-08-22 — Session 1 (Phase 0)

**Done:** full repo skeleton per §7; `requirements.txt`; `.env.example` from
§13; `.gitignore`; Makefile + PowerShell shims; real `config.py`, `db.py`,
`models.py`, `main.py`; every other backend module as a signature-only stub;
Next.js 14.2.35 + Tailwind 3.4 + shadcn/ui scaffold with `lib/api.ts` and a
stub page at `/`; `SCHEMA.md`; this log. Gate verified end to end.

**Key decisions:**

- **Python 3.14, not the 3.11 in §6.** 3.11 was not installed and 3.14 was;
  the team chose to proceed on 3.14 rather than spend setup time. Vindicated —
  every dependency installed, and only WeasyPrint fails to import, for a reason
  unrelated to the Python version (missing GTK, see Gotchas). *§6 stack table
  should be read as "Python 3.11+" until someone updates it.*
- **Makefile kept AND PowerShell shims added.** `make` is not on the dev
  machine but the Makefile is what runs on Ubuntu in Phase 8, so both exist and
  do the same three things. No dependency added.
- **`schedule.end_date` is INCLUSIVE.** §8 writes `end_date = start_date +
  duration_days`, which yields an 8th day of doses for a 7-day course. Stored
  as `start_date + duration_days - 1` instead: a 7-day course starting
  2026-08-22 ends 2026-08-28, giving exactly `duration_days × len(dose_times)`
  doses. This is what "7-day course" means to a caretaker and what reads
  correctly on the doctor PDF. **Phase 2's materialiser and Phase 6's course-end
  check must both treat it as inclusive** (`end_date < today` means the course
  is over).
- **11 tables, not 9.** §8's prose says "Eleven tables" and lists eleven; the
  Phase 0 prompt in §14 says "all nine tables from §8". Built all eleven, since
  the named list is unambiguous and `medicine_reference` and `report` are both
  required by later phases.
- **Multiple caretakers per patient is handled by `family`, not a join table.**
  §4.10 wants many caretakers on one patient; §8 fixes the table count at
  eleven and puts `relation` on `caretaker`. So caretakers and patients both
  belong to a family and every caretaker in a family sees that family's
  patients. No twelfth table invented (§4: delete abstractions for use cases
  that do not exist).
- **`patient_id` denormalised onto `dose_event`.** The dashboard polls today's
  doses every 5 seconds; without it that is a three-table join on every poll.
- **Stubs raise `NotImplementedError("Phase N — …")` rather than `pass`.** §0
  forbids placeholder code, §14 Phase 0 explicitly asks for signature-only
  modules. Raising satisfies both: the contract is frozen and callable, and
  nothing can silently return a wrong answer.
- **`reports/caretaker_pdf.py` was NOT created.** §7's file layout does not list
  it, and §0 says stay inside that layout — but Phase 6 explicitly requires it.
  It gets created in Phase 6. Flagging so nobody thinks it was forgotten.
- **`GET /api/health` reports rather than asserts.** The app boots and returns
  200 with an empty `DATABASE_URL`, listing what is missing, instead of
  crashing. Without this the Phase 0 gate could not be verified before Supabase
  existed, and a paused Supabase project would take the whole demo down at the
  wrong moment.
- **shadcn components pre-added:** `button`, `card`, `table`, `badge` (the four
  §14 Phase 4 names), plus `input`, `label`, `select` for the add-patient and
  add-medicine forms. Adding them now means Phase 4 needs no network.

**Blockers hit:** none that stopped work. `shadcn init -d` and the WeasyPrint
import both failed and are recorded in Gotchas with their resolutions.

**Before touching this area next:** `models.py` is **frozen**. There is no
Alembic — `create_all` only creates missing tables, it never alters one. If a
column genuinely must change after the first real boot, drop that table in
Supabase by hand and let it recreate, and log why.
