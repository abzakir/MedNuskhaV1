# The WhatsApp bridge - Node + Baileys, owns the socket.
#
# Deliberately dumb: no business logic, no database. It exposes /send/text,
# /send/audio and /status, and forwards every inbound message to the backend
# webhook (AGENTS.md invariant 6).
#
# AUTH_DIR MUST be a mounted volume. It holds a real WhatsApp login - anyone
# with that folder can read the account's messages - and if it is lost the
# number has to be re-paired by scanning a QR code, which cannot be done
# unattended. See docker-compose.yml.

FROM node:20-slim

ENV NODE_ENV=production

WORKDIR /srv

# Baileys is pinned to a release candidate on purpose: 6.17.16 cannot resolve
# LID senders, so it cannot tell who replied (PROJECT_LOG.md, Session 5).
# `npm ci` needs the lockfile to honour that pin.
COPY package.json package-lock.json* ./
RUN npm ci --omit=dev || npm install --omit=dev

COPY index.js ./

ENV AUTH_DIR=/srv/auth_info
RUN mkdir -p /srv/auth_info && chown -R node:node /srv
USER node

EXPOSE 3001

# "connected" is the only state that can actually send. `qr` means it is
# waiting to be paired and `logged_out` means the device was unlinked - both
# need a human, so failing the health check on them is correct.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD node -e "fetch('http://127.0.0.1:3001/status').then(r=>r.json()).then(s=>process.exit(s.state==='connected'?0:1)).catch(()=>process.exit(1))"

CMD ["node", "index.js"]
