# Deploying ASPIRE to a VPS

Assumes Ubuntu 24.04 (Debian 12 works; note the Python step). The site is
`aspire.eccugenai.app`; that hostname is already written into
`nginx-aspire.conf`, so there is nothing to substitute.

Point an `A` record (and `AAAA`, if the VPS has IPv6) at the server before
starting section 6 — certbot proves control over the name by being reachable at
it, so it fails until DNS resolves.

## What you are running

Three processes behind one hostname:

| Process | Port | What it is |
| --- | --- | --- |
| `aspire-api` | 127.0.0.1:8000 | FastAPI — `/chat`, `/api/voice/*` |
| `aspire-web` | 127.0.0.1:3000 | Node — server-renders the app's HTML |
| `nginx` | 443 | TLS, serves `/srv/aspire-web/client/`, routes the rest |

Only nginx is exposed. Both app processes bind to loopback.

## Two things that will bite you

**1. The API URL is compiled into the JavaScript.** `VITE_ASPIRE_API_URL` is
read by Vite at *build* time and the literal string is written into the client
bundle. It is not read at runtime, and setting it in a systemd unit does
nothing. Changing it means rebuilding. Verify after every build:

```bash
grep -o 'https://aspire.eccugenai.app' dist/client/assets/*.js | head -1
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
# The repository is public, so this needs no credentials. If you ever make it
# private, switch to the SSH remote and add a deploy key — see section 8.
sudo -u aspire git clone https://github.com/fraimerdev/aspire-chatbot.git /srv/aspire
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
CORS_ALLOW_ORIGINS=["https://aspire.eccugenai.app"]
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
sudo -u aspire env VITE_ASPIRE_API_URL="https://aspire.eccugenai.app" bun run build
```

Confirm the URL was baked in:

```bash
grep -o 'https://aspire.eccugenai.app' dist/client/assets/*.js | head -1
```

Empty output means the build used the default `http://localhost:8000` and the
deployed app will try to call the user's own machine.

nginx does not serve `dist/client` directly — it serves `/srv/aspire-web/client`,
a symlink that only moves once a build has succeeded. Publish this first build
by hand; from then on `deploy/update.sh` does it:

```bash
sudo mkdir -p /srv/aspire-web && sudo chown aspire:aspire /srv/aspire-web
sudo -u aspire cp -a dist/client /srv/aspire-web/client.a
sudo -u aspire ln -sfn /srv/aspire-web/client.a /srv/aspire-web/client
```

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

## 7. Verify

```bash
curl -sI https://aspire.eccugenai.app/ | head -1                                  # 200
curl -s https://aspire.eccugenai.app/ | grep -c 'learn about money'               # 1 → SSR works
curl -sI https://aspire.eccugenai.app/assets/$(ls /srv/aspire-web/client/assets/index-*.js | xargs -n1 basename) | head -1
curl -s -X POST https://aspire.eccugenai.app/chat -H 'Content-Type: application/json' \
     -d '{"message":"What is ASPIRE?","thread_id":null,"simple_mode":false}' | head -c 300
curl -s https://aspire.eccugenai.app/api/voice/config | head -c 200               # only if VOICE_ENABLED
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

## 8. Deploying on every push

`.github/workflows/deploy.yml` runs on every push to `main`. It does no
building of its own — it opens an SSH session and runs the script from the
previous section, so the Actions log *is* that script's output and a hand-run
deploy and an automatic one are the same thing.

One key is involved, in one direction — GitHub reaching the box:

```
GitHub Actions  --ssh(DEPLOY_SSH_KEY)-->  VPS as `aspire`
VPS             --https---------------->  github.com  (public repo, no credentials)
```

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

Then let it restart the two units, and only those:

```bash
echo 'aspire ALL=(root) NOPASSWD: /usr/bin/systemctl restart aspire-api aspire-web' \
  | sudo tee /etc/sudoers.d/aspire-deploy
sudo chmod 440 /etc/sudoers.d/aspire-deploy
sudo visudo -c
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
`journalctl -u aspire-api -u aspire-web -n 100 --no-pager`.

### What this does not do

- **Migrations run before the restart and are not rolled back.** A migration
  that drops something the previous version needs makes rollback-by-redeploy
  insufficient. Keep them additive.
- **In-flight conversations are dropped on every deploy**, for the reason in
  "Two things that will bite you". Auto-deploy means this now happens on every
  push to `main` rather than when you chose it.
- **Nothing gates the deploy on tests.** There is no test job in the workflow
  yet; `main` goes to production as-is.
- **It restarts two units.** If the arq worker (`arq app.jobs.WorkerSettings`,
  needed once `MEMORY_WINDOW_ENABLED` is on) becomes a third service, add it to
  the `systemctl restart` line in `update.sh` *and* to `/etc/sudoers.d/aspire-deploy`
  — the sudo rule matches the whole command, so it will fail closed otherwise.

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
