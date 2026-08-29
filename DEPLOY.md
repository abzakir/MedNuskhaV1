# Deploying MedNuskha

Backend and WhatsApp bridge on **Oracle Cloud Always Free**, dashboard on
**Vercel**. Written for someone who has not deployed a server before.

About an hour, most of it waiting. Cost: nothing, permanently.

---

## What goes where, and why

| Piece | Where | Why |
|---|---|---|
| **Dashboard** (Next.js) | Vercel | Static pages and a browser app — exactly what Vercel is for |
| **Backend** (FastAPI) | Oracle VM | The scheduler ticks every minute forever. A dose due at 08:00 must fire whether or not anyone has the site open — serverless cannot do that. |
| **WhatsApp bridge** (Node) | the same VM | Holds a live WebSocket to WhatsApp plus 2,000+ session files on disk. No serverless platform anywhere can hold an open socket. |
| **Database** | Supabase | Already hosted. Nothing to do. |

### Two things checked in advance

**ARM works.** Oracle's free tier is ARM (Ampere). Every dependency that
compiles — `ctranslate2`, `av`, `psycopg`, `uharfbuzz` — publishes a Linux
`aarch64` wheel for Python 3.11, which is what the Dockerfile uses. Nothing
builds from source.

**A small box is enough.** The 605MB local Whisper model is a *fallback*;
Groq's `whisper-large-v3` is primary. Voice notes work fine without it.

---

## Part 1 — the Oracle VM

### 1.1 Sign up

<https://cloud.oracle.com> → Start for free.

A card is required for identity checks. **You are not charged** as long as you
stay on Always Free resources, and the account cannot silently upgrade — it
stops rather than bills you. When the trial credits expire the Always Free
resources keep running.

Pick a **home region** close to you — Singapore or Mumbai from Pakistan. This
cannot be changed later.

### 1.2 Create the instance

Menu → **Compute → Instances → Create instance**.

- **Name**: `mednuskha`
- **Image**: click *Change image* → **Canonical Ubuntu 22.04**
- **Shape**: click *Change shape* → **Ampere** → `VM.Standard.A1.Flex`
  - **4 OCPUs, 24 GB memory** — all free, so take all of it
- **SSH keys**: *Generate a key pair for me* → **download the private key**.
  You cannot download it again.
- **Create**

> **If you see "Out of host capacity"** — the free ARM shape is popular and
> regions fill up. Two ways through: try again over a few hours (capacity
> frees constantly), or switch the shape to `VM.Standard.E2.1.Micro` (AMD,
> 1 OCPU / 1 GB, also free forever). The 1GB box is enough for this project
> as long as you skip the local Whisper model — see 1.7.

Note the **Public IP address** when it finishes provisioning.

### 1.3 Open the firewall — BOTH of them

This is where most Oracle deploys stall. There are **two** firewalls and
opening only one leaves you staring at a connection that never completes.

**First, the cloud one.** Instance page → *Virtual cloud network* → *Security
Lists* → *Default Security List* → **Add Ingress Rules**:

| Source CIDR | Protocol | Destination port |
|---|---|---|
| `0.0.0.0/0` | TCP | `80` |
| `0.0.0.0/0` | TCP | `443` |

Do **not** open 8000 or 3001. The bridge will message anyone who asks it to.

**Second, the one on the machine itself.** Oracle's Ubuntu images ship with
iptables rules that drop everything except SSH. After you connect in 1.4:

```bash
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 80 -j ACCEPT
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 443 -j ACCEPT
sudo netfilter-persistent save
```

### 1.4 Connect

```bash
chmod 600 ssh-key-*.key
ssh -i ssh-key-*.key ubuntu@YOUR_PUBLIC_IP
```

On Windows, run this from Git Bash. The username is `ubuntu`, not `root`.

### 1.5 Install Docker

```bash
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker ubuntu
exit
```

Log back in for the group change to apply, then check:

```bash
ssh -i ssh-key-*.key ubuntu@YOUR_PUBLIC_IP
docker ps
```

### 1.6 Get the code

```bash
git clone https://github.com/abzakir/MedNuskhaV1.git
cd MedNuskhaV1
```

A private repo will ask for credentials — use a GitHub personal access token
as the password, not your account password.

### 1.7 Configuration

Copy your `.env` up **from your laptop**, in a second terminal:

```bash
scp -i ssh-key-*.key C:/Users/ASUS/Desktop/MedNuskha/.env ubuntu@YOUR_IP:~/MedNuskhaV1/.env
```

Back on the server, change three values:

```bash
nano .env
```

```
DEV_AUTH_BYPASS=false
NEXT_PUBLIC_API_BASE=https://api.yourdomain.com
ALLOWED_NUMBERS=923200268481,923255159422
```

- **`DEV_AUTH_BYPASS=false`** is the one that matters. Left `true`, every
  unauthenticated request to a public API is treated as a signed-in caretaker.
- **`NEXT_PUBLIC_API_BASE`** is what the backend builds report links from.
  Leave it as `localhost` and every link a caretaker taps is dead.
- **`ALLOWED_NUMBERS`** — empty means *no restriction*. Set it, or a mistyped
  number reaches a stranger.

*On the 1GB AMD shape only*, also drop the local Whisper model so the image
stays small — Groq handles transcription anyway:

```bash
sed -i '/faster-whisper/d' backend/requirements.txt
```

### 1.8 Bring your WhatsApp session with you

**The step people miss.** Pairing needs a QR code scanned from the phone that
owns the number — you cannot do that over SSH afterwards. Your laptop already
has a working session, so copy it instead of re-pairing.

From your laptop:

```bash
cd C:/Users/ASUS/Desktop/MedNuskha/whatsapp-bridge
tar czf auth.tgz auth_info
scp -i ~/ssh-key-*.key auth.tgz ubuntu@YOUR_IP:~/
```

On the server:

```bash
cd ~ && tar xzf auth.tgz
docker volume create mednuskhav1_whatsapp-auth
docker run --rm -v mednuskhav1_whatsapp-auth:/dst -v ~/auth_info:/src alpine \
  sh -c "cp -a /src/. /dst/"
rm -rf ~/auth_info ~/auth.tgz
```

> **A WhatsApp account links to one bridge at a time.** Starting the server
> bridge knocks your laptop's offline. That is expected — do not run both.

### 1.9 Start it

```bash
cd ~/MedNuskhaV1
docker compose up -d --build
docker compose logs -f backend
```

The first build takes 5–10 minutes. Wait for `Application startup complete`,
then Ctrl-C out of the logs and check:

```bash
curl localhost:8000/api/health
```

You want `"database":"connected"`, `"scheduler":"running"`,
`"whatsapp":{"state":"connected"}`.

If WhatsApp says `qr`, the session did not copy — redo 1.8.

### 1.10 HTTPS

You need it. Supabase will not redirect OAuth to a plain-HTTP origin, and a
secure Vercel page cannot call an insecure API — the browser blocks it.

**Get a domain first.** A `.xyz` is about a dollar from Namecheap or
Cloudflare. Add an **A record** for `api` pointing at your public IP. A
self-signed certificate on a bare IP will cost you more debugging time than
the domain costs money.

Then:

```bash
sudo apt install -y debian-keyring debian-archive-keyring apt-transport-https curl
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | sudo tee /etc/apt/sources.list.d/caddy-stable.list
sudo apt update && sudo apt install -y caddy
sudo nano /etc/caddy/Caddyfile
```

Replace the whole file with:

```
api.yourdomain.com {
    reverse_proxy localhost:8000
}
```

```bash
sudo systemctl restart caddy
curl https://api.yourdomain.com/api/health
```

Caddy obtains and renews the certificate on its own.

---

## Part 2 — the dashboard on Vercel

```bash
cd C:/Users/ASUS/Desktop/MedNuskha/frontend
npx vercel login
npx vercel --prod
```

Accept the defaults; Next.js is detected automatically.

Then in the Vercel dashboard → your project → **Settings → Environment
Variables**, add all three for **Production**:

```
NEXT_PUBLIC_API_BASE           https://api.yourdomain.com
NEXT_PUBLIC_SUPABASE_URL       https://jhustfytfatkrlqudgcz.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY  (the sb_publishable_ key from your .env)
```

**Then redeploy.** `NEXT_PUBLIC_*` values are compiled in at build time, so a
build that ran before you set them still points at `localhost:8000`.

```bash
npx vercel --prod
```

> The production build has already been verified locally — all 9 routes
> compile, so a failure here is configuration, not code.

---

## Part 3 — tell Supabase the new address

Authentication → **URL Configuration**:

- **Site URL**: `https://your-project.vercel.app`
- **Redirect URLs** — add both, keep localhost for development:
  ```
  https://your-project.vercel.app/**
  http://localhost:3000/**
  ```

Google sign-in and password reset both bounce through here. Without it,
sign-in succeeds and then lands nowhere.

**The Google Cloud redirect URI does not change** — it points at Supabase, not
at your app.

---

## Part 4 — prove it works

```bash
curl https://api.yourdomain.com/api/health
```

Then on the Vercel URL: sign in, open a patient, add a medicine with a dose
time three minutes out, and watch a real reminder reach a real phone.

That is the only test that proves the whole chain — the VM, the bridge, the
scheduler, the session, the numbers and the tunnel between Vercel and Oracle.

---

## Before you call it done

- [ ] `DEV_AUTH_BYPASS=false` on the server
- [ ] `ALLOWED_NUMBERS` set to your demo numbers only
- [ ] `NEXT_PUBLIC_API_BASE` is the HTTPS URL in **both** `.env` and Vercel
- [ ] Ports 8000 and 3001 are **not** in the Oracle security list
- [ ] `/api/health` returns connected / running / connected
- [ ] A live reminder arrived on a real phone
- [ ] The WhatsApp volume is backed up:

```bash
docker run --rm -v mednuskhav1_whatsapp-auth:/src -v ~:/dst alpine \
  tar czf /dst/whatsapp-auth-backup.tgz -C /src .
```

That volume is the one piece of state here that cannot be rebuilt from
anything else. Losing it means re-pairing by QR, with the phone in your hand.

---

## When something breaks

**Cannot SSH** — the private key must be `chmod 600`, and the user is
`ubuntu`.

**Site never loads, no error** — the instance iptables rules from 1.3. Almost
always this.

**`whatsapp: "qr"`** — the session did not copy. Redo 1.8, or
`docker compose logs -f bridge` and scan the QR once with the phone.

**`database: "error"`** — Supabase free projects pause after about a week
idle. Open the Supabase dashboard and it wakes.

**Dashboard loads, every request fails** — `NEXT_PUBLIC_API_BASE` is wrong, or
was set after the last build. Fix it and redeploy.

**Reminders never fire** — `curl localhost:8000/api/health`. If `scheduler` is
not `running`, another process holds the Postgres advisory lock: stop the
backend on your laptop.

**Everything looks right but nothing arrives** — `ALLOWED_NUMBERS`. A wrong
value drops sends silently.

**Out of memory on the 1GB shape** — you kept `faster-whisper`. Remove it
(1.7) and rebuild; Groq does the transcription anyway.
