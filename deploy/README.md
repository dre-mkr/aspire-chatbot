# Deploying ASPIRE to a VPS

Assumes Ubuntu 24.04 (Debian 12 works; note the Python step). The site is
`aspire.eccugenai.app`; that hostname is already written into
`nginx-aspire.conf`, so there is nothing to substitute.

Point an `A` record (and `AAAA`, if the VPS has IPv6) at the server before
starting section 7 — certbot proves control over the name by being reachable at
it, so it fails until DNS resolves.

## What you are running

Four processes and one datastore behind one hostname, plus Postgres off-box:

| Process | Port | What it is |
| --- | --- | --- |
| `aspire-api` | 127.0.0.1:8000 | FastAPI — `/v2/*`, `/api/*` |
| `aspire-web` | 127.0.0.1:3000 | Node — server-renders the app's HTML |
| `aspire-worker` | — | arq — nightly retention, summarisation |
| `valkey` | 127.0.0.1:6380 | arq's queue and the response cache |
| `nginx` | 443 | TLS, serves `/srv/aspire-web/client/`, routes the rest |
| Neon Postgres | (remote) | Conversations, accounts, applications, graph state |

Only nginx is exposed. Everything else binds to loopback.

Process management is **pm2**, defined once in `ecosystem.config.cjs`. The
systemd units that used to live here were deleted: two ways to start the same
three processes is a way to end up running six, fighting over two ports.

## Four things that will bite you

**1. The API URL is compiled into the JavaScript.** `VITE_ASPIRE_API_URL` is
read by Vite at *build* time and the literal string is written into the client
bundle. It is not read at runtime, and setting it in `ecosystem.config.cjs` does
nothing. Changing it means rebuilding. Verify after every build:

```bash
grep -o 'https://aspire.eccugenai.app' dist/client/assets/*.js | head -1
```

Because nginx serves the API on the same hostname, this is just your site URL.

**2. The admin API lives under `/api/admin`, and it must stay there.** The
portal's *pages* are TanStack routes at `/admin`, `/admin/applications` and
`/admin/widgets`. The backend serves the matching *data* endpoints. With both on
one hostname and both at `/admin/applications`, nginx cannot tell a page request
from a data request — whichever upstream wins, the other 404s. Keeping the API
under `/api/` means the existing proxy rule catches it and there is nothing to
disambiguate. If you ever move that router prefix, this config breaks.

**3. The backend must run exactly one worker.** `--workers 1` in
`ecosystem.config.cjs` is load-bearing. The rate limiter in `app/limits.py` is
an in-process counter, by a documented decision: a per-process window IS the
whole service's window only while there is one process. A second worker silently
doubles every limit on the endpoints that spend model credits. Scaling past one
process means moving those counters to Valkey *and* making them fail closed
first — `app/limits.py` says so in its docstring.

**4. Conversations survive a restart; in-flight turns do not.** Graph state is
LangGraph's `AsyncPostgresSaver` in Neon, keyed by session, so a deploy does not
lose anybody's history — a half-finished registration resumes days later. What a
restart does drop is the turn currently streaming, and the rate-limit windows.
Both are acceptable; neither is a data loss. (This is a change from an earlier
in-process checkpointer. If `DATABASE_URL` is unset the app falls back to an
in-memory saver and the old "history dies on restart" behaviour returns, which
is a supported test configuration and not a production one.)

## 1. Server preparation

```bash
sudo adduser --system --group --home /srv/aspire aspire
sudo mkdir -p /srv/aspire && sudo chown aspire:aspire /srv/aspire

sudo apt update
sudo apt install -y nginx git curl

# Node 22 LTS — runs the SSR server and pm2
curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash -
sudo apt install -y nodejs
sudo npm install -g pm2

# bun — the frontend's lockfile is bun.lock, so this is what installs and builds.
# (package-lock.json is gitignored, so `npm ci` cannot work here.)
curl -fsSL https://bun.sh/install | sudo BUN_INSTALL=/usr/local bash

# uv, which also supplies Python 3.13 (the backend needs >=3.12; Ubuntu 24.04
# ships 3.12 and Debian 12 ships 3.11, so let uv own the version either way)
sudo curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR=/usr/local/bin sh
```

### Valkey

The arq worker refuses to start without it (`app/jobs.py` raises naming
`VALKEY_URL`), and the response cache uses the same instance. Ubuntu 24.04 does
not package Valkey yet; Redis is wire-compatible with everything used here, so
either is fine:

```bash
sudo apt install -y redis-server        # or valkey-server where packaged
```

Put it on **6380**, not the default 6379, to match `.env.example` and to avoid
colliding with anything already on this box:

```bash
sudo sed -i 's/^port 6379/port 6380/' /etc/redis/redis.conf
```

Then give it a memory ceiling. `app/limits.py` records that the Valkey this
project has used was shared with an unrelated application, uncapped and set to
`noeviction` — which is how a cache fills a disk and starts refusing writes to
everything sharing it:

```bash
sudo tee -a /etc/redis/redis.conf >/dev/null <<'EOF'
maxmemory 256mb
maxmemory-policy allkeys-lru
EOF
sudo systemctl enable --now redis-server
redis-cli -p 6380 ping        # PONG
```

`allkeys-lru` rather than `noeviction` is deliberate: everything stored here is
a cache entry or a queued job that can be re-derived. Refusing writes when full
would take the worker down; evicting the coldest key does not.

## 2. Get the code onto the box

```bash
# The repository is public, so this needs no credentials. If you ever make it
# private, switch to the SSH remote and add a deploy key — see section 9.
sudo -u aspire git clone https://github.com/fraimerdev/aspire-chatbot.git /srv/aspire
```

## 3. Database

Postgres is Neon, not local. Create a database, then take the **pooled**
connection string — the host with `-pooler` in it. `.env.example` explains why
at length: the direct endpoint holds one backend per connection and the app's
per-request session pool will exhaust it. The app warns at startup if the URL
does not look pooled.

`pgvector` is installed per database, not per project; migration `0001` runs
`CREATE EXTENSION IF NOT EXISTS vector`, so the migration step below covers it.

## 4. Backend

```bash
cd /srv/aspire/backend
sudo -u aspire uv sync --frozen           # creates .venv from uv.lock
sudo -u aspire cp .env.example .env
sudo -u aspire nano .env
sudo chmod 600 .env
```

The values with no working default — the app either fails loudly or silently
loses a feature without each of these:

```ini
OPENAI_API_KEY=sk-...
CHAT_MODEL=openai:gpt-5.6-luna
CORS_ALLOW_ORIGINS=["https://aspire.eccugenai.app"]
LOG_LEVEL=INFO

DATABASE_URL=postgresql://user:pass@ep-xxxx-pooler.region.aws.neon.tech/aspire
VALKEY_URL=redis://localhost:6380

# Signs every session token. No default on purpose: a signing key with a
# fallback is a signing key everyone who read the source also has. Without it
# every /api/auth/* call answers 500.
#   python -c "import secrets; print(secrets.token_urlsafe(48))"
SESSION_SECRET=

# Encrypts application_pii. Registration refuses to persist a national ID or a
# date of birth without it, rather than writing plaintext.
#   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
PII_ENCRYPTION_KEY=

# Registration document uploads go browser-to-bucket via a presigned URL and
# never through FastAPI. Unset means uploads answer 503.
S3_ENDPOINT_URL=
S3_BUCKET=aspire-documents
S3_REGION=us-east-1
S3_ACCESS_KEY_ID=
S3_SECRET_ACCESS_KEY=

# Only if you want voice. All four ids are required when this is true —
# a missing one is a deliberate hard startup failure.
VOICE_ENABLED=true
ELEVENLABS_API_KEY=...
VOICE_STELLA=...
VOICE_ORION=...
VOICE_AURORA=...
VOICE_NOVA=...
```

Run the migrations, then build the vector store. The service ingests on first
boot if the store is empty, but doing it by hand surfaces a bad API key now
rather than as a failed startup:

```bash
sudo -u aspire .venv/bin/alembic upgrade head
sudo -u aspire .venv/bin/python -m app.ingest
```

`data/` must stay writable — it holds `chroma/` and `voice_cache/`.

### The first admin account

There is no "register as staff" endpoint and there will not be one. Seed the
first reviewer from the shell; it prints a generated password once and forces a
change at first sign-in:

```bash
sudo -u aspire .venv/bin/python -m app.api.admin.staff create you@example.com --role admin
```

## 5. Frontend

```bash
cd /srv/aspire/frontend
sudo -u aspire bun install --frozen-lockfile
sudo -u aspire env VITE_ASPIRE_API_URL="https://aspire.eccugenai.app" bun run build
```

Confirm the URL was baked in:

```bash
grep -o 'https://aspire.eccugenai.app' dist/client/assets/*.js | head -1
```

Empty output means the build used the default `http://localhost:8000` and the
deployed app will try to call the visitor's own machine.

nginx does not serve `dist/client` directly — it serves `/srv/aspire-web/client`,
a symlink that only moves once a build has succeeded. Publish this first build
by hand; from then on `deploy/update.sh` does it:

```bash
sudo mkdir -p /srv/aspire-web && sudo chown aspire:aspire /srv/aspire-web
sudo -u aspire cp -a dist/client /srv/aspire-web/client.a
sudo -u aspire ln -sfn /srv/aspire-web/client.a /srv/aspire-web/client
```

## 6. Start the processes

pm2 runs **as the `aspire` user**, not as root. That is what lets the deploy
restart these processes over SSH without a sudo rule.

`PM2_HOME` is set explicitly for the same reason `update.sh` sets it: pm2
resolves its daemon through that variable, and a deploy that sees a different
value talks to a second, empty daemon — reporting success while the processes
actually serving traffic keep running the old code.

```bash
echo 'export PM2_HOME=/srv/aspire/.pm2' | sudo -u aspire tee -a /srv/aspire/.bashrc

cd /srv/aspire
sudo -u aspire env PM2_HOME=/srv/aspire/.pm2 pm2 start deploy/ecosystem.config.cjs
sudo -u aspire env PM2_HOME=/srv/aspire/.pm2 pm2 save
sudo -u aspire env PM2_HOME=/srv/aspire/.pm2 pm2 status
```

Bring them back after a reboot. `pm2 startup` prints one command; run it exactly
as printed — it embeds the user and `PM2_HOME`:

```bash
sudo -u aspire env PM2_HOME=/srv/aspire/.pm2 pm2 startup systemd -u aspire --hp /srv/aspire
```

Log rotation is not on by default and a small VPS will fill its disk:

```bash
sudo -u aspire env PM2_HOME=/srv/aspire/.pm2 pm2 install pm2-logrotate
sudo -u aspire env PM2_HOME=/srv/aspire/.pm2 pm2 set pm2-logrotate:max_size 10M
sudo -u aspire env PM2_HOME=/srv/aspire/.pm2 pm2 set pm2-logrotate:retain 7
```

`pm2 restart` does **not** rebuild. After a `git pull` the frontend must be
rebuilt before restarting, or you will serve the previous bundle. `update.sh`
does both in the right order.

Check all three answer:

```bash
curl -s localhost:8000/health          # {"status":"ok"}
curl -sI localhost:3000/ | head -1     # HTTP/1.1 200 OK
sudo -u aspire env PM2_HOME=/srv/aspire/.pm2 pm2 status   # three apps, "online"
```

## 7. nginx and TLS

```bash
sudo cp /srv/aspire/deploy/nginx-aspire.conf /etc/nginx/sites-available/aspire
sudo ln -s /etc/nginx/sites-available/aspire /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl reload nginx

sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d aspire.eccugenai.app
```

Certbot rewrites the listen lines and adds the HTTP redirect. Renewal is
automatic via its systemd timer.

Firewall, if you use one:

```bash
sudo ufw allow OpenSSH && sudo ufw allow 'Nginx Full' && sudo ufw enable
```

## 8. Verify

```bash
# The page renders
curl -sI https://aspire.eccugenai.app/ | head -1                      # 200
curl -s  https://aspire.eccugenai.app/ | grep -c 'learn about money'  # 1 → SSR works

# A session mints
curl -s -X POST https://aspire.eccugenai.app/v2/session | head -c 200

# The chat route reaches FastAPI and not the renderer. This is the single most
# important check on this page: unauthenticated, the API answers a JSON 401.
# HTML back means nginx sent it to the SSR process and chat is broken.
curl -s -X POST https://aspire.eccugenai.app/v2/chat/stream \
     -H 'Content-Type: application/json' -d '{}' | head -c 200
# expect: {"code":"unauthenticated","message":"Please sign in again to keep chatting."}

# The admin API is reachable at /api/admin and the admin PAGE at /admin.
curl -s -o /dev/null -w '%{http_code}\n' https://aspire.eccugenai.app/api/admin/applications   # 401
curl -s -o /dev/null -w '%{content_type}\n' https://aspire.eccugenai.app/admin                 # text/html

curl -s https://aspire.eccugenai.app/api/voice/config | head -c 200    # only if VOICE_ENABLED
```

Then open the site and send a real message. If voice is on, record something —
that exercises the upload path, where nginx's body-size limit would otherwise
show up as "Voice is offline".

## Updating

One script does the whole sequence — fetch, dependencies, migrations, build,
publish, restart, health check:

```bash
sudo -u aspire /srv/aspire/deploy/update.sh
```

It is written to be safe to interrupt and safe to re-run. Two properties worth
knowing:

- It **resets** the checkout to `origin/main`. Local edits on the box are
  discarded. It never runs `git clean`, because `backend/.env` and
  `backend/data/` are untracked by design.
- Nothing user-visible changes until the build has succeeded *and* the compiled
  bundle has been checked for your domain. A failed build leaves the previous
  version serving.

It reads its settings from `/etc/aspire-deploy.env`, which lives outside the
checkout so a deploy cannot rewrite what drives the deploy:

```ini
SITE_URL=https://aspire.eccugenai.app
# BRANCH=main
# REPO_DIR=/srv/aspire
# WEB_ROOT=/srv/aspire-web
# PM2_HOME=/srv/aspire/.pm2
```

`SITE_URL` has no default. Without it the script refuses to build rather than
bake in a guess.

To roll back, point the checkout at the last good commit and re-run:

```bash
sudo -u aspire env TARGET=<good-sha> /srv/aspire/deploy/update.sh
```

The next push to `main` will move it forward again, so revert the commit on
GitHub too rather than leaving the box pinned.

Re-run `python -m app.ingest` only when `data/knowledge_base.csv` changed.
Changing `EMBEDDINGS_MODEL` or `EMBEDDINGS_PROVIDER` changes the vector
dimensions and makes the existing store unreadable — delete `data/chroma` and
re-ingest.

## 9. Deploying on every push

`.github/workflows/deploy.yml` runs on every push to `main`. It does no
building of its own — it opens an SSH session and runs the script from the
previous section, so the Actions log *is* that script's output and a hand-run
deploy and an automatic one are the same thing.

One key is involved, in one direction — GitHub reaching the box:

```
GitHub Actions  --ssh(DEPLOY_SSH_KEY)-->  VPS as `aspire`
VPS             --https---------------->  github.com  (public repo, no credentials)
```

### GitHub needs to be able to reach the VPS

The `aspire` user was created with `--system`, which gives it no login shell.
Give it one, and authorise a key that exists only for this purpose:

```bash
sudo usermod -s /bin/bash aspire
sudo -u aspire install -d -m 700 /srv/aspire/.ssh

# Generate this on your own machine, not the server: the private half has to
# leave the box exactly once, into GitHub's secret store.
ssh-keygen -t ed25519 -N '' -f ~/.ssh/aspire_deploy -C 'github-actions -> aspire vps'
```

Append the **public** half to `/srv/aspire/.ssh/authorized_keys`, restricted so
a leaked key cannot open an interactive session or forward ports:

```
restrict,command="/srv/aspire/deploy/update.sh" ssh-ed25519 AAAA... github-actions
```

That forced command is the whole authorisation story. Under pm2 there is **no
sudoers rule at all**: the deploy restarts processes owned by the same user it
logs in as, so a leaked deploy key cannot restart anything else on the box, and
adding an app to `ecosystem.config.cjs` needs no privilege change. (If you are
migrating a box that ran the old systemd units, delete
`/etc/sudoers.d/aspire-deploy` and the units in `/etc/systemd/system/aspire-*`
once pm2 is serving, or the two will fight for the ports.)

### If the repository ever becomes private

Skip this while it is public. The VPS would then need its own read-only key:
generate one owned by `aspire` and add the **public** half at *Settings → Deploy
keys → Add deploy key* (leave "Allow write access" unchecked):

```bash
sudo -u aspire ssh-keygen -t ed25519 -N '' -f /srv/aspire/.ssh/id_github
sudo -u aspire cat /srv/aspire/.ssh/id_github.pub

sudo -u aspire tee -a /srv/aspire/.ssh/config >/dev/null <<'EOF'
Host github.com
    IdentityFile /srv/aspire/.ssh/id_github
    IdentitiesOnly yes
EOF

# the remote must be the SSH form for that key to be used
sudo -u aspire git -C /srv/aspire remote set-url origin git@github.com:OWNER/REPO.git
sudo -u aspire git -C /srv/aspire fetch origin      # accepts the host key, proves it works
```

### Repository secrets

*Settings → Secrets and variables → Actions → New repository secret:*

| Secret | Value |
| --- | --- |
| `DEPLOY_HOST` | the server's hostname or IP |
| `DEPLOY_USER` | `aspire` |
| `DEPLOY_SSH_KEY` | contents of `~/.ssh/aspire_deploy` — the whole file, `BEGIN`/`END` lines included |
| `DEPLOY_KNOWN_HOSTS` | output of `ssh-keyscan -t ed25519 YOUR-HOST` |
| `DEPLOY_PORT` | only if sshd is not on 22 |

`DEPLOY_KNOWN_HOSTS` is not optional busywork. The alternative is a runner that
accepts whatever host key it is offered, which means handing that private key to
whoever answers at that address.

### First run

Push to `main`, or trigger it from *Actions → Deploy → Run workflow*. Failures
are loud by construction: the script exits non-zero if the domain is missing
from the built bundle, or if either service fails to answer on loopback within
a minute, and the job goes red.

If the deploy is green but the site is wrong, the box is the place to look —
`pm2 logs --lines 100 --nostream`.

### What this does not do

- **Migrations run before the restart and are not rolled back.** A migration
  that drops something the previous version needs makes rollback-by-redeploy
  insufficient. Keep them additive.
- **The turn currently streaming is dropped on every deploy.** Saved history is
  not: it is in Neon. Auto-deploy means this now happens on every push to
  `main` rather than when you chose it.
- **The deploy is gated on tests.** `.github/workflows/deploy.yml` runs a
  `verify` job — typecheck, lint, backend suite, production build — and the
  deploy job will not start unless it passes.
- **It restarts all three apps**, via `pm2 startOrReload` on
  `ecosystem.config.cjs`. `aspire-worker` is not optional: `app/jobs.py`
  registers the retention cron that enforces the 180-day deletion commitment in
  `backend/PRIVACY.md`, and nothing else runs it. (It also hosts the
  summarisation job, which only has work when `MEMORY_WINDOW_ENABLED` is on —
  that flag does not make the app optional.)

  Because the deploy uses `startOrReload`, adding an app to the ecosystem file
  is picked up on the next push with no action on the box.

  The retention job will not clear an existing backlog until 03:15. To sweep
  immediately once, after checking what it would delete:

  ```sh
  cd /srv/aspire/backend
  .venv/bin/python -c "import asyncio; from app.retention import sweep_anonymous; \
      print(asyncio.run(sweep_anonymous(dry_run=True)))"
  ```

## Operating notes

- **Logs:** `pm2 logs aspire-api`, `pm2 logs aspire-worker`, `pm2 logs aspire-web`.
  Remember `PM2_HOME` if you are not in the `aspire` user's shell.
- **Cost:** every message is several model calls, and transcription is billed
  per request with keyterms adding 20%. The per-caller limits in `app/limits.py`
  are abuse dampening, not authentication — anonymous chat is a supported path,
  so anyone with the URL can spend your API credits. Consider Cloudflare in
  front, or a private DNS name, until that changes.
- **Backups:** `backend/.env` (secrets, not in git) and
  `backend/data/knowledge_base.csv` (the source of truth). Neon holds the
  conversations, accounts and applications and has its own backups — check its
  retention setting. `data/chroma` is derived and can be rebuilt;
  `data/voice_cache` is disposable.
- **Memory:** Chroma plus the embedding client wants roughly 1 GB, and Valkey is
  capped at 256 MB above. A 2 GB VPS is comfortable; 1 GB will be tight during
  ingest.
- **Scaling past one box** means moving the rate limiter to Valkey and making it
  fail closed first. Until then, add CPU rather than workers.
