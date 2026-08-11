# Deploying ASPIRE to a VPS

Assumes Ubuntu 24.04 (Debian 12 works; note the Python step). The site is
`aspire.eccugenai.app`; that hostname is already written into
`nginx-aspire.conf`, so there is nothing to substitute.

Point an `A` record (and `AAAA`, if the VPS has IPv6) at the server before
starting section 7 — a certificate authority proves control over the name by
reaching it, so that step fails until DNS resolves.

This deployment sits **behind Cloudflare**, which changes how TLS is obtained
and how the app sees client addresses. Section 7 covers both; skipping the
`nginx-cloudflare-realip.conf` step there leaves every visitor sharing one
rate-limit bucket.

## What you are running

Four processes and one datastore behind one hostname, plus Postgres off-box:

| Process | Port | What it is |
| --- | --- | --- |
| `aspire-api` | 127.0.0.1:8000 | FastAPI — `/v2/*`, `/api/*` |
| `aspire-web` | 127.0.0.1:3000 | Node — server-renders the app's HTML |
| `aspire-worker` | — | arq — nightly retention, summarisation |
| `valkey` | 127.0.0.1:6380 | arq's queue and the response cache |
| `nginx` | 443 | TLS, serves `/aspire-web/client/`, routes the rest |
| Neon Postgres | (remote) | Conversations, accounts, applications, graph state, and the pgvector corpus |

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

Everything here runs as **root**. There is no separate service account: the
checkout lives in root's home, pm2's daemon is root's own `~/.pm2`, and the
deploy logs in as root. What bounds a leaked deploy key is therefore not a Unix
user but the forced command in `authorized_keys` — see section 9. If you later
want the unprivileged-user model back, the pieces that would need to change are
`ROOT` in `ecosystem.config.cjs`, `REPO_DIR`/`PM2_HOME` in `update.sh`, and the
ownership of `/aspire-web`.

```bash
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
sudo git clone https://github.com/fraimerdev/aspire-chatbot.git /root/aspire
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
cd /root/aspire/backend
sudo uv sync --frozen           # creates .venv from uv.lock
sudo cp .env.example .env
sudo nano .env
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
sudo .venv/bin/alembic upgrade head
sudo .venv/bin/python -m app.ingest
```

Retrieval is **pgvector in Neon**, not a local store: `app/ingest.py` writes the
embedded corpus to the `documents` table, and `app/rag.py` queries it there. The
local Chroma directory that older notes mention is gone — the only thing left of
it is `chroma_floor_as_cosine_distance()`, which translates the old relevance
threshold. So a rebuild of the vector store costs one embedding run against
OpenAI and touches nothing on disk.

`data/` must still stay writable — it holds `voice_cache/` and `events/`.

### The first admin account

There is no "register as staff" endpoint and there will not be one. Seed the
first reviewer from the shell; it prints a generated password once and forces a
change at first sign-in:

```bash
sudo .venv/bin/python -m app.api.admin.staff create you@example.com --role admin
```

## 5. Frontend

```bash
cd /root/aspire/frontend
sudo bun install --frozen-lockfile
sudo env VITE_ASPIRE_API_URL="https://aspire.eccugenai.app" bun run build
```

Confirm the URL was baked in:

```bash
grep -o 'https://aspire.eccugenai.app' dist/client/assets/*.js | head -1
```

Empty output means the build used the default `http://localhost:8000` and the
deployed app will try to call the visitor's own machine.

nginx does not serve `dist/client` directly — it serves `/aspire-web/client`,
a symlink that only moves once a build has succeeded. Publish this first build
by hand; from then on `deploy/update.sh` does it:

```bash
sudo mkdir -p /aspire-web
sudo cp -a dist/client /aspire-web/client.a
sudo ln -sfn /aspire-web/client.a /aspire-web/client
```

## 6. Start the processes

pm2 runs as root, and its daemon lives at `/root/.pm2` — root's *default*
`$HOME/.pm2`. That is deliberate. pm2 resolves its daemon through `PM2_HOME`,
and a shell that sees a different value talks to a second, empty daemon:
the deploy reports success having reloaded nothing, while the processes actually
serving traffic keep running the old code. Leaving it at the default means a
bare `pm2 status` in any root shell reaches the right daemon with no
environment variable at all. `update.sh` still names it explicitly, because
sshd runs a forced command in a non-login shell where `HOME` is not guaranteed.

```bash
cd /root/aspire
pm2 start deploy/ecosystem.config.cjs
pm2 save
pm2 status
```

Bring them back after a reboot. `pm2 startup` prints one command; run it exactly
as printed — it embeds the user and `PM2_HOME`:

```bash
pm2 startup systemd -u root --hp /root
```

Log rotation is not on by default and a small VPS will fill its disk:

```bash
pm2 install pm2-logrotate
pm2 set pm2-logrotate:max_size 10M
pm2 set pm2-logrotate:retain 7
```

`pm2 restart` does **not** rebuild. After a `git pull` the frontend must be
rebuilt before restarting, or you will serve the previous bundle. `update.sh`
does both in the right order.

Check all three answer:

```bash
curl -s localhost:8000/health          # {"status":"ok"}
curl -sI localhost:3000/ | head -1     # HTTP/1.1 200 OK
pm2 status                             # three apps, "online"
```

## 7. nginx and TLS

```bash
sudo cp /root/aspire/deploy/nginx-aspire.conf /etc/nginx/sites-available/aspire
sudo ln -s /etc/nginx/sites-available/aspire /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default

# Cloudflare sits in front of this name, so restore the visitor's real address
# before anything reads it. Section "Cloudflare" below says why this matters.
sudo cp /root/aspire/deploy/nginx-cloudflare-realip.conf \
        /etc/nginx/conf.d/cloudflare-realip.conf

sudo nginx -t && sudo systemctl reload nginx
```

### Cloudflare

`aspire.eccugenai.app` is a **proxied** (orange-cloud) record. Two consequences
that are easy to miss and expensive to diagnose:

**Certificates are two hops, not one.** The certificate a browser sees is
Cloudflare's, issued for the edge. The certificate nginx presents is only ever
seen by Cloudflare, and which one it will accept depends on the zone's SSL/TLS
mode:

| Cloudflare mode | What the origin needs on :443 |
| --- | --- |
| Flexible | nothing — Cloudflare talks to :80 (don't: the last hop is plaintext) |
| Full | any certificate, self-signed included |
| Full (strict) | a publicly-trusted cert, or a Cloudflare Origin certificate |

If nothing listens on origin :443 you get **521** from the edge; if something
listens but the cert is not acceptable for the mode, **526**.

**Getting a certificate needs :443 working first.** There is a chicken-and-egg
here that is worth understanding before you debug it at 2am. HTTP-01 needs
Let's Encrypt to reach `/.well-known/acme-challenge/` over plain HTTP; with
*Always Use HTTPS* on, Cloudflare answers that with a 301 to HTTPS at the edge
and then tries the origin on :443. If nothing is listening there yet, validation
fails — so you cannot get the certificate that would make :443 work.

Break it with a throwaway self-signed pair, which "Full" mode accepts:

```bash
sudo install -d -m 700 /etc/ssl/aspire
sudo openssl req -x509 -nodes -newkey rsa:2048 -days 3650 \
     -keyout /etc/ssl/aspire/privkey.pem \
     -out    /etc/ssl/aspire/fullchain.pem \
     -subj "/CN=aspire.eccugenai.app" \
     -addext "subjectAltName=DNS:aspire.eccugenai.app"
```

Point `ssl_certificate` at that, reload, and :443 answers. Now HTTP-01 works
straight through the proxy — this is the method in use, and its renewal is
verified by `certbot renew --dry-run`:

```bash
sudo apt install -y certbot
sudo install -d -m 755 /var/www/acme
sudo certbot certonly --webroot -w /var/www/acme -d aspire.eccugenai.app \
     --email you@example.com --agree-tos --no-eff-email
```

`certonly`, not `--nginx`, on purpose: `--nginx` rewrites this repo's config
file in place, so the copy in git and the copy nginx reads drift apart and the
next `cp` from the repo silently reverts the certificate paths. With `certonly`
you set `ssl_certificate` to `/etc/letsencrypt/live/<domain>/fullchain.pem`
once, in the file, and certbot never touches it.

One thing certbot does not do for you: **nginx keeps the old certificate in
memory across a renewal.** Without a deploy hook the renewal "succeeds" and the
site starts serving an expired certificate 60 days later.

```bash
sudo tee /etc/letsencrypt/renewal-hooks/deploy/reload-nginx.sh >/dev/null <<'EOF'
#!/bin/sh
systemctl reload nginx
EOF
sudo chmod +x /etc/letsencrypt/renewal-hooks/deploy/reload-nginx.sh
```

If HTTP-01 ever stops working (Cloudflare settings change, or you want to drop
port 80 entirely), the two alternatives are a **Cloudflare Origin certificate**
(dashboard → SSL/TLS → Origin Server; free, 15 years, valid for Full (strict),
never publicly trusted — which does not matter because only Cloudflare sees it)
or **DNS-01** via `certbot --dns-cloudflare` with a Zone:DNS:Edit token.

Once a publicly-trusted certificate is installed, set the zone to
**Full (strict)**. Leaving it on "Full" means Cloudflare accepts *any* origin
certificate, which is barely better than no verification at all.

Firewall, if you use one:

```bash
sudo ufw allow OpenSSH && sudo ufw allow 'Nginx Full' && sudo ufw enable
```

Because every legitimate request arrives from Cloudflare, you can go further
and refuse everything else — worth doing, since the origin IP is discoverable
and an attacker who has it can bypass Cloudflare's WAF and rate limiting
entirely:

```bash
for cidr in $(curl -s https://www.cloudflare.com/ips-v4) \
            $(curl -s https://www.cloudflare.com/ips-v6); do
    sudo ufw allow from "$cidr" to any port 443 proto tcp
done
sudo ufw delete allow 'Nginx Full'
```

Keep port 80 open to everyone only if you are renewing by HTTP-01.

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
sudo /root/aspire/deploy/update.sh
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
# REPO_DIR=/root/aspire
# WEB_ROOT=/aspire-web
# PM2_HOME=/root/.pm2
```

`SITE_URL` has no default. Without it the script refuses to build rather than
bake in a guess.

To roll back, point the checkout at the last good commit and re-run:

```bash
sudo env TARGET=<good-sha> /root/aspire/deploy/update.sh
```

The next push to `main` will move it forward again, so revert the commit on
GitHub too rather than leaving the box pinned.

Re-run `python -m app.ingest` only when `data/knowledge_base.csv` changed. It
replaces the rows in the `documents` table and flushes the response cache, so
there is nothing to delete first.

Changing `EMBEDDINGS_MODEL` or `EMBEDDINGS_PROVIDER` changes the vector width,
which the `documents.embedding` column is typed to. That needs a migration to
alter the column, not just a re-ingest — treat it as a schema change.

## 9. Deploying on every push

`.github/workflows/deploy.yml` runs on every push to `main`. It does no
building of its own — it opens an SSH session and runs the script from the
previous section, so the Actions log *is* that script's output and a hand-run
deploy and an automatic one are the same thing.

One key is involved, in one direction — GitHub reaching the box:

```
GitHub Actions  --ssh(DEPLOY_SSH_KEY)-->  VPS as `root`
VPS             --https---------------->  github.com  (public repo, no credentials)
```

### GitHub needs to be able to reach the VPS

Authorise a key that exists only for this purpose:

```bash
sudo install -d -m 700 /root/.ssh

# Generate this on your own machine, not the server: the private half has to
# leave the box exactly once, into GitHub's secret store.
ssh-keygen -t ed25519 -N '' -f ~/.ssh/aspire_deploy -C 'github-actions -> aspire vps'
```

Append the **public** half to `/root/.ssh/authorized_keys`, restricted so
a leaked key cannot open an interactive session or forward ports:

```
restrict,command="/root/aspire/deploy/update.sh" ssh-ed25519 AAAA... github-actions
```

**That forced command is the entire authorisation story, and here it is doing
all of the work.** The key logs in as root, so `restrict` and `command=` are
the only things standing between a leaked deploy key and the whole machine.
Two habits follow from that:

- Never drop the `command=` prefix "just to debug something". Open a second,
  ordinary key for yourself instead and delete it when you are done.
- Treat write access to `main` as equivalent to root on this box, because it
  is: `update.sh` runs whatever `main` says it should. Protect the branch.

There is no sudoers rule and no separate service account to keep in step —
which is the upside of this arrangement, and the reason adding an app to
`ecosystem.config.cjs` needs no privilege change on the box. (If you are
migrating a box that ran the old systemd units, delete
`/etc/sudoers.d/aspire-deploy` and the units in `/etc/systemd/system/aspire-*`
once pm2 is serving, or the two will fight for the ports.)

### If the repository ever becomes private

Skip this while it is public. The VPS would then need its own read-only key:
generate one and add the **public** half at *Settings → Deploy
keys → Add deploy key* (leave "Allow write access" unchecked):

```bash
sudo ssh-keygen -t ed25519 -N '' -f /root/.ssh/id_github
sudo cat /root/.ssh/id_github.pub

sudo tee -a /root/.ssh/config >/dev/null <<'EOF'
Host github.com
    IdentityFile /root/.ssh/id_github
    IdentitiesOnly yes
EOF

# the remote must be the SSH form for that key to be used
sudo git -C /root/aspire remote set-url origin git@github.com:OWNER/REPO.git
sudo git -C /root/aspire fetch origin      # accepts the host key, proves it works
```

### Repository secrets

*Settings → Secrets and variables → Actions → New repository secret:*

| Secret | Value |
| --- | --- |
| `DEPLOY_HOST` | the server's hostname or IP |
| `DEPLOY_USER` | `root` |
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
  cd /root/aspire/backend
  .venv/bin/python -c "import asyncio; from app.retention import sweep_anonymous; \
      print(asyncio.run(sweep_anonymous(dry_run=True)))"
  ```

## Operating notes

- **Logs:** `pm2 logs aspire-api`, `pm2 logs aspire-worker`, `pm2 logs aspire-web`.
  These reach the right daemon from any root shell; `PM2_HOME` defaults to
  `/root/.pm2`, which is where they live.
- **Cost:** every message is several model calls, and transcription is billed
  per request with keyterms adding 20%. The per-caller limits in `app/limits.py`
  are abuse dampening, not authentication — anonymous chat is a supported path,
  so anyone with the URL can spend your API credits. Cloudflare is already in
  front; turn on Bot Fight Mode and a rate-limiting rule there if this starts
  costing real money, since the edge can refuse a request for free and this box
  cannot.
- **Backups:** `backend/.env` (secrets, not in git) and
  `backend/data/knowledge_base.csv` (the source of truth). Neon holds the
  conversations, accounts, applications *and* the embedded corpus, and has its
  own backups — check its retention setting. The `documents` table is derived
  from the CSV and can be rebuilt with `python -m app.ingest`;
  `data/voice_cache` is disposable.
- **Memory:** the vector store is off-box now, so the API process is mostly the
  model clients; Valkey is capped at 256 MB above. A 2 GB VPS is comfortable.
- **Scaling past one box** means moving the rate limiter to Valkey and making it
  fail closed first. Until then, add CPU rather than workers.
