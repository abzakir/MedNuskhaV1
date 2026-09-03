# MedNuskha backend - FastAPI, the scheduler, the agent and the webhook.
#
# The WhatsApp bridge is a separate Node service in whatsapp-bridge/ with its
# own Dockerfile; docker-compose.yml runs the pair. This image does NOT include
# the Next.js dashboard, which deploys to Vercel (AGENTS.md section 6).
#
# Deliberately has no system packages beyond ca-certificates:
#   - PDFs are fpdf2, which is pure Python. Dropping WeasyPrint took GTK and
#     Pango out of this file (PROJECT_LOG.md, Session 8).
#   - Audio is PyAV, which ships its own FFmpeg libraries in the wheel. No
#     ffmpeg binary is needed for either direction of voice.
# If you find yourself adding apt packages here, check whether a dependency
# changed before you add them.

FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Requirements first, so a code change does not re-download 300MB of wheels.
COPY backend/requirements.txt ./requirements.txt
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY backend/app ./app

# Pre-generated voice notes live here. Mount a volume over it in production -
# without one they are re-synthesised after every deploy, which works but
# means the first reminder for each medicine goes out as text while the
# background task catches up. See docker-compose.yml.
ENV VOICE_CACHE_DIR=/app/.voice-cache
RUN mkdir -p /app/.voice-cache

# The local Whisper model is downloaded on first use and cached here. Same
# reasoning: mount it, or the first inbound voice note pays for the download.
ENV HF_HOME=/app/.cache/huggingface
RUN mkdir -p /app/.cache/huggingface

# Nothing here needs root once the wheels are installed.
RUN useradd --create-home --uid 10001 mednuskha \
    && chown -R mednuskha:mednuskha /app
USER mednuskha

EXPOSE 8000

# /api/health reports the database, the scheduler, the WhatsApp connection and
# how many AI keys are alive - so an orchestrator restarting on it is checking
# something real, not just that the process is up.
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD python -c "import os,urllib.request,sys; \
port=os.environ.get('PORT','8000'); \
sys.exit(0 if urllib.request.urlopen(f'http://127.0.0.1:{port}/api/health', timeout=4).status == 200 else 1)"

# One worker on purpose. A Postgres advisory lock already stops a second
# process running the ticker (PROJECT_LOG.md, Session 3), so extra workers
# would serve requests but sit idle on the schedule - and the lock failure
# reads like a bug to whoever finds it next. Scale with more containers behind
# a load balancer if the API ever needs it.
# ${PORT:-8000} rather than a fixed 8000: every PaaS assigns a port and
# routes to it, and a container listening somewhere else never passes
# its health check. Compose sets no PORT, so it stays on 8000 there.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1"]
