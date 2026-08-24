# MedNuskha

An AI care agent that keeps elderly patients on their medication, delivered
entirely over WhatsApp — so the patient installs nothing and learns nothing.

A caretaker signs up on the website and adds a family member and their
medicines. The patient gets a WhatsApp reminder at every dose, with an Urdu
voice note. They reply however they like — typed or spoken, Urdu script, Roman
Urdu or English — and the agent understands it. Silence escalates to the
caretaker. When a course ends, two PDFs are generated: a clinical one for the
doctor and a plain-language one for the family.

---

## Architecture

```
   PATIENT                 CARETAKER
   (WhatsApp only)         (browser + WhatsApp)
        |                       |
        |  text / voice note    |  sign in
        v                       v
  +-------------+        +------------------+
  |  WhatsApp   |        |  Dashboard       |
  |  (Baileys)  |        |  Next.js  :3000  |  --> Vercel
  +-------------+        +------------------+
        |  ^                    |
   POST |  | send               |  REST + Supabase JWT
        v  |                    v
  +--------------------------------------------------+
  |  BRIDGE :3001        |        BACKEND :8000       |
  |  Node + Baileys      |        FastAPI             |
  |  owns the socket     |<------>|                   |
  |  no business logic   | /send  |  webhook  ------+ |
  +----------------------+--------+                 | |
                                  |  agent          | |
                                  |   interpret ----+ |
                                  |   respond         |
                                  |   guardrails      |
                                  |   knowledge       |
                                  |                   |
                                  |  scheduler        |
                                  |   ticker (1 min)  |
                                  |   course-end job  |
                                  |                   |
                                  |  voice   reports  |
                                  +---------+---------+
                                            |
                    +-----------------------+------------------+
                    |                |                |        |
                    v                v                v        v
              Supabase          Groq / Qwen      edge-tts   faster-whisper
              Postgres +        (pooled keys)    (Urdu TTS)  (local ASR)
              Storage
```

Three processes and one hosted database:

| Process | Port | What it is |
|---|---|---|
| Dashboard | 3000 | Next.js 14 — the caretaker's website |
| Backend | 8000 | FastAPI — API, scheduler, agent, webhook, reports |
| WhatsApp bridge | 3001 | Node + Baileys — owns the WhatsApp socket |
| Supabase | — | Postgres 17 (11 tables) + Storage, hosted |

The bridge exists because Baileys is Node-only and the backend is Python. It is
deliberately dumb — no business logic, no database — so swapping WhatsApp
providers touches two files, not the system.

---

## Prerequisites

- **Python 3.11+** (developed on 3.14; the container is 3.11)
- **Node 20+**
- **A Supabase project** — free tier is plenty
- **A phone with WhatsApp** to pair the bridge to, once
- No Docker needed for development. No ffmpeg, no GTK — see *Why there are no
  system dependencies* below.

---

## Setup

### 1. Clone and install

```bash
git clone https://github.com/abzakir/MedNuskha.git
cd MedNuskha
make install          # or: .\install.ps1 on Windows
```

That creates `backend/.venv`, installs the Python requirements, and runs
`npm install` in `frontend/`.

### 2. Configure

```bash
cp .env.example .env
```

`.env.example` documents every variable, what it is for, and where to get it.
The ones you cannot start without:

| Variable | Where it comes from |
|---|---|
| `DATABASE_URL` | Supabase → Project Settings → Database → Connection string (**session pooler**) |
| `SUPABASE_URL`, `SUPABASE_ANON_KEY` | Supabase → Project Settings → API keys |
| `GROQ_API_KEY` | console.groq.com — free. Comma-separate several to widen the pool |
| `WEBHOOK_SECRET` | Invent one. Any long random string |

Worth setting, but not blocking:

| Variable | Why |
|---|---|
| `SUPABASE_SERVICE_KEY` | The `sb_secret_` key. Without it nothing is archived to Storage — reports are rebuilt on each open and voice notes are re-synthesised after each deploy. Both still work. |
| `ALLOWED_NUMBERS` | The bridge will message **anyone** when this is empty. Set it on any deployed instance. |
| `DEV_AUTH_BYPASS` | `true` locally treats unauthenticated requests as a fixed caretaker. **Must be `false` in production.** |

Nothing else needs an account: `edge-tts` reaches Microsoft's neural voices
with no key, and `faster-whisper` runs locally.

### 3. Pair WhatsApp, once

```bash
make bridge           # or: .\bridge.ps1
```

Scan the QR code from the phone that owns the number. The session is written to
`whatsapp-bridge/auth_info/`, which is gitignored and **is a real WhatsApp
login** — anyone holding that folder can read the account's messages. Never
commit it, never share it.

### 4. Run everything

```bash
make dev              # or: .\dev.ps1  (this one also starts the bridge)
```

- Dashboard — http://localhost:3000
- Health — http://localhost:8000/api/health

`/api/health` reports the database, the scheduler, the WhatsApp connection and
how many AI keys are alive, in one call. Check it first when something is off.

### 5. Seed a demo

```bash
make seed             # or: .\seed.ps1
```

One caretaker, one patient, three real medicines and 14 days of backdated doses
with a believable mix of taken, late and missed — so the dashboard and both
PDFs have something worth showing immediately.

It attaches to whichever caretaker signed in most recently, so sign in once
first. Safe to run twice; `--purge-only` removes it again.

```bash
python scripts/seed_demo.py --phone 923001234567   # a LIVE demo: this number
                                                   # starts getting reminders
```

---

## Tests

```bash
make test                                       # 107 unit tests, no services
python scripts/verify/verify_credentials.py     # is every key actually working?
```

`scripts/verify/` holds ~310 integration checks against the live database,
live Groq and the live bridge — they are how each phase was actually proven.
`scripts/verify/README.md` says what each one covers.

---

## Deployment

The dashboard goes to Vercel; the backend and bridge go on one small box.

### Backend + bridge

```bash
docker compose up -d --build
docker compose logs -f bridge     # first run only: scan the QR code
```

On a fresh host the bridge has no WhatsApp session and prints a QR code. Scan
it once; the session persists in the `whatsapp-auth` volume.

Then put TLS in front of the backend — Caddy is two lines and handles renewal:

```
api.yourdomain.com {
    reverse_proxy localhost:8000
}
```

Before going live:

- `DEV_AUTH_BYPASS=false` — otherwise every unauthenticated request is treated
  as a caretaker.
- `ALLOWED_NUMBERS` — set it, or a mis-typed number reaches a stranger.
- `NEXT_PUBLIC_API_BASE` — the public HTTPS URL. Report links sent over
  WhatsApp are built from this, so if it still says `localhost:8000` every link
  a caretaker taps is dead.
- Back up the `whatsapp-auth` volume. Losing it means re-pairing by QR, which
  cannot be done unattended.

### Dashboard

```bash
cd frontend && vercel --prod
```

Set `NEXT_PUBLIC_API_BASE` to the backend's HTTPS URL in Vercel's environment
settings, and the Supabase URL and anon key alongside it.

---

## Why there are no system dependencies

Two deliberate choices, both of which removed an apt line and a class of
"works on my machine":

- **PDFs use fpdf2, not WeasyPrint.** WeasyPrint needs GTK and Pango, which pip
  does not ship on Windows — it could not even import on the dev machine. The
  Urdu fonts are committed to the repo rather than taken from the system, so a
  bare Ubuntu box renders exactly what was signed off.
- **Audio uses PyAV, not an ffmpeg binary.** PyAV bundles FFmpeg's libraries in
  its wheel and handles both directions — MP3 to OGG/Opus going out, decoding
  going in.

If you find yourself adding `apt install` to the Dockerfile, check whether a
dependency changed first.

---

## Where things are

```
backend/app/
  whatsapp/      client, webhook, parser — the only modules that talk to WhatsApp
  scheduler/     ticker (every minute), state_machine (the only writer of dose state)
  agent/         interpret, respond, guardrails, knowledge, llm, caretaker
  voice/         asr (faster-whisper), tts (edge-tts), store
  reports/       data, doctor_pdf, caretaker_pdf, service, storage
  api/routes.py  REST for the dashboard
frontend/        Next.js dashboard
whatsapp-bridge/ Node + Baileys
scripts/verify/  integration checks
```

`AGENTS.md` is the specification — invariants, phase plan, conventions.
`PROJECT_LOG.md` is the running history: what was decided, what broke, and
every measurement that shaped a design. Read both before changing anything.

---

## Safety

This is a medication reminder, not a medical device. Three rules are enforced in
code rather than by convention:

- **The agent never gives medical advice.** Guardrails run on the outbound text,
  after the model has spoken — a system prompt can be talked around, a regex
  over the final message cannot.
- **It only repeats caretaker-confirmed information.** There is no code path
  from a patient's question to a live model call about a medicine.
- **Nothing claims a dose was observed.** Every report states in full that these
  are patient-reported confirmations, not observed ingestion.
