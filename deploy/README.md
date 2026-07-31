# Deploying ASPIRE to a VPS

Assumes Ubuntu 24.04 (Debian 12 works; note the Python step). Replace
`aspire.example.com` with your domain throughout.

## What you are running

Three processes behind one hostname:

| Process | Port | What it is |
| --- | --- | --- |
| `aspire-api` | 127.0.0.1:8000 | FastAPI — `/chat`, `/api/voice/*` |
| `aspire-web` | 127.0.0.1:3000 | Node — server-renders the app's HTML |
| `nginx` | 443 | TLS, serves `dist/client/`, routes the rest |

Only nginx is exposed. Both app processes bind to loopback.

## Two things that will bite you

**1. The API URL is compiled into the JavaScript.** `VITE_ASPIRE_API_URL` is
read by Vite at *build* time and the literal string is written into the client
bundle. It is not read at runtime, and setting it in a systemd unit does
nothing. Changing it means rebuilding. Verify after every build:

```bash
grep -o 'https://aspire.example.com' dist/client/assets/*.js | head -1
```

Because nginx serves the API on the same hostname, this is just your site URL.

**2. The backend must run exactly one worker.** Conversation memory is a
langgraph `InMemorySaver` and the voice rate limiter is a process-local dict.
With two workers, a follow-up question can land on the process that never saw
the first one — the assistant loses the thread, intermittently, in a way that
looks like a model problem. `--workers 1` in the unit file is load-bearing.

A corollary: **conversations do not survive a restart.** Memory is in-process,
so every deploy drops in-flight threads. Users see a working app with no
history; the rail's saved conversations are in the browser's localStorage and
are unaffected.

## 1. Server preparation

```bash
sudo adduser --system --group --home /srv/aspire aspire
sudo mkdir -p /srv/aspire && sudo chown aspire:aspire /srv/aspire

sudo apt update
sudo apt install -y nginx git curl

# Node 22 LTS — runs the SSR server
curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash -
sudo apt install -y nodejs

# bun — the frontend's lockfile is bun.lock, so this is what installs and builds.
# (There is no package-lock.json, so `npm ci` cannot work here.)
curl -fsSL https://bun.sh/install | sudo BUN_INSTALL=/usr/local bash

# uv, which also supplies Python 3.13 (the backend needs >=3.12; Ubuntu 24.04
# ships 3.12 and Debian 12 ships 3.11, so let uv own the version either way)
sudo curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR=/usr/local/bin sh
```

## 2. Get the code onto the box

```bash
sudo -u aspire git clone <your-repo> /srv/aspire
# or: rsync -av --exclude node_modules --exclude .venv --exclude dist ./ user@vps:/srv/aspire/
```

## 3. Backend

```bash
cd /srv/aspire/backend
sudo -u aspire uv sync --frozen           # creates .venv from uv.lock
sudo -u aspire cp .env.example .env
sudo -u aspire nano .env
sudo chmod 600 .env
```

Set in `.env`:

```ini
OPENAI_API_KEY=sk-...
CORS_ALLOW_ORIGINS=["https://aspire.example.com"]
LOG_LEVEL=INFO

# Only if you want voice. All four ids are required when this is true —
# a missing one is a deliberate hard startup failure.
VOICE_ENABLED=true
ELEVENLABS_API_KEY=...
VOICE_STELLA=...
VOICE_ORION=...
VOICE_AURORA=...
VOICE_NOVA=...
```

Build the vector store. The service does this automatically on first boot if the
store is empty, but doing it by hand surfaces a bad API key now rather than as a
failed startup:

```bash
sudo -u aspire .venv/bin/python -m app.ingest
```

`data/` must stay writable — it holds `chroma/` and `voice_cache/`. It is the
only path the unit file grants write access to.

## 4. Frontend

```bash
cd /srv/aspire/frontend
sudo -u aspire bun install --frozen-lockfile
sudo -u aspire env VITE_ASPIRE_API_URL="https://aspire.example.com" bun run build
```

Confirm the URL was baked in:

```bash
grep -o 'https://aspire.example.com' dist/client/assets/*.js | head -1
```

Empty output means the build used the default `http://localhost:8000` and the
deployed app will try to call the user's own machine.

## 5. Services

Two options. Use one, not both — they will fight over the ports.

### With pm2

```bash
cd /srv/aspire
pm2 start deploy/ecosystem.config.cjs
pm2 save                # without this, nothing comes back after a reboot
pm2 startup             # prints one command to run as root; run it
pm2 status
```

Log rotation is not on by default and a small VPS will fill its disk:

```bash
pm2 install pm2-logrotate
pm2 set pm2-logrotate:max_size 10M
pm2 set pm2-logrotate:retain 7
```

`pm2 restart` does **not** rebuild. After a `git pull` the frontend must be
rebuilt before restarting, or you will serve the previous bundle.

### With systemd

```bash
sudo cp /srv/aspire/deploy/aspire-{api,web}.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now aspire-api aspire-web
sudo systemctl status aspire-api aspire-web --no-pager
```

### Either way, check both answer on loopback

```bash
curl -s localhost:8000/health          # {"status":"ok"}
curl -sI localhost:3000/ | head -1     # HTTP/1.1 200 OK
```

## 6. nginx and TLS

```bash
sudo cp /srv/aspire/deploy/nginx-aspire.conf /etc/nginx/sites-available/aspire
sudo sed -i 's/aspire.example.com/YOUR-DOMAIN/g' /etc/nginx/sites-available/aspire
sudo ln -s /etc/nginx/sites-available/aspire /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl reload nginx

sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d YOUR-DOMAIN
```

Certbot rewrites the listen lines and adds the HTTP redirect. Renewal is
automatic via its systemd timer.

Firewall, if you use one:

```bash
sudo ufw allow OpenSSH && sudo ufw allow 'Nginx Full' && sudo ufw enable
```

## 7. Verify

```bash
curl -sI https://YOUR-DOMAIN/ | head -1                                  # 200
curl -s https://YOUR-DOMAIN/ | grep -c 'learn about money'               # 1 → SSR works
curl -sI https://YOUR-DOMAIN/assets/$(ls /srv/aspire/frontend/dist/client/assets/index-*.js | xargs -n1 basename) | head -1
curl -s -X POST https://YOUR-DOMAIN/chat -H 'Content-Type: application/json' \
     -d '{"message":"What is ASPIRE?","thread_id":null,"simple_mode":false}' | head -c 300
curl -s https://YOUR-DOMAIN/api/voice/config | head -c 200               # only if VOICE_ENABLED
```

Then open the site and send a real message. If voice is on, record something —
that exercises the upload path, where nginx's body-size limit would otherwise
show up as "Voice is offline".

## Updating

```bash
cd /srv/aspire && sudo -u aspire git pull

cd backend && sudo -u aspire uv sync --frozen
cd ../frontend && sudo -u aspire bun install --frozen-lockfile \
  && sudo -u aspire env VITE_ASPIRE_API_URL="https://YOUR-DOMAIN" bun run build

# pm2
pm2 restart aspire-api aspire-web
# or systemd
sudo systemctl restart aspire-api aspire-web
```

The rebuild is not optional. `pm2 restart` restarts the process; it does not run
Vite, so skipping the build step above leaves the old bundle on disk and nginx
keeps serving it.

Re-run `python -m app.ingest` only when `data/knowledge_base.csv` changed.
Changing `EMBEDDINGS_MODEL` or `EMBEDDINGS_PROVIDER` changes the vector
dimensions and makes the existing store unreadable — delete `data/chroma` and
re-ingest.

## Operating notes

- **Logs:** `pm2 logs aspire-api` / `pm2 logs aspire-web`, or under systemd
  `journalctl -u aspire-api -f`.
- **Cost:** every message is several model calls, and transcription is billed
  per request with keyterms adding 20%. The per-session rate limits in `.env`
  are abuse dampening, not authentication — there is no auth on this service, so
  anyone with the URL can spend your API credits. Consider Cloudflare in front,
  basic auth in nginx, or a private DNS name until that changes.
- **Backups:** `backend/.env` (secrets, not in git) and
  `backend/data/knowledge_base.csv` (the source of truth). `data/chroma` is
  derived and can be rebuilt; `data/voice_cache` is disposable.
- **Memory:** Chroma plus the embedding client wants roughly 1 GB. A 2 GB VPS is
  comfortable; 1 GB will be tight during ingest.
- **Scaling past one box** means replacing the in-process checkpointer and rate
  limiter with shared storage first. Until then, add CPU rather than workers.
