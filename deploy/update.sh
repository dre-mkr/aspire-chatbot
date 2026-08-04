#!/usr/bin/env bash
#
# Bring the running app up to match origin/main. Invoked by GitHub Actions over
# SSH (see .github/workflows/deploy.yml), and safe to run by hand on the box:
#
#   sudo -u aspire /srv/aspire/deploy/update.sh
#
# Configuration lives in /etc/aspire-deploy.env, deliberately outside the git
# checkout so a deploy can never rewrite the settings that drive the deploy.
#
set -euo pipefail

# --- run from a copy ---------------------------------------------------------
# This script resets the repository that contains this script. bash reads a
# script incrementally, so rewriting the file mid-run makes it resume at a byte
# offset into different text. Re-exec from a private copy first; the copy
# unlinks itself immediately, which is safe because bash keeps its fd open.
if [ "${ASPIRE_DEPLOY_REEXEC:-}" != "1" ]; then
    _self=$(mktemp /tmp/aspire-deploy.XXXXXX)
    cp -- "$0" "$_self"
    chmod +x -- "$_self"
    ASPIRE_DEPLOY_REEXEC=1 exec "$_self" "$@"
fi
case "$0" in /tmp/aspire-deploy.*) rm -f -- "$0" ;; esac

# --- configuration -----------------------------------------------------------
# sshd runs a forced command in a non-login shell, so none of the usual profile
# scripts have run. uv and bun both install to /usr/local/bin; say so rather
# than depend on what sshd happens to hand us.
export PATH=/usr/local/bin:/usr/bin:/bin

CONFIG_FILE=${ASPIRE_DEPLOY_CONFIG:-/etc/aspire-deploy.env}
if [ -r "$CONFIG_FILE" ]; then
    # shellcheck disable=SC1090
    . "$CONFIG_FILE"
fi

REPO_DIR=${REPO_DIR:-/srv/aspire}
WEB_ROOT=${WEB_ROOT:-/srv/aspire-web}
BRANCH=${BRANCH:-main}
# What to check out. Overridable so a rollback can name a commit directly:
#   sudo -u aspire env TARGET=<sha> /srv/aspire/deploy/update.sh
TARGET=${TARGET:-origin/$BRANCH}

# Baked into the JavaScript at build time, not read at runtime. Getting this
# wrong ships a bundle that calls the visitor's own machine, so refuse to build
# rather than guess.
: "${SITE_URL:?SITE_URL is not set. Put SITE_URL=https://your-domain in $CONFIG_FILE}"

log() { printf '\n=== %s\n' "$*"; }

# --- one deploy at a time ----------------------------------------------------
exec 9>/run/lock/aspire-deploy.lock
if ! flock -n 9; then
    echo "another deploy is already running; giving up" >&2
    exit 1
fi

cd "$REPO_DIR"

# --- source ------------------------------------------------------------------
log "Fetching $TARGET"
before=$(git rev-parse HEAD)
git fetch --prune origin
git reset --hard "$TARGET"
after=$(git rev-parse HEAD)
git --no-pager log --oneline -1

# Note for whoever edits this next: do NOT add `git clean`. backend/.env and
# backend/data/ are untracked by design — the secrets and the vector store —
# and a clean would delete both.

# --- backend -----------------------------------------------------------------
log "Backend dependencies"
cd "$REPO_DIR/backend"
uv sync --frozen

# Migrations, once this checkout has them and a database is configured. Both
# conditions are checked so the script works unchanged before and after the
# database work lands on main.
if [ -f alembic.ini ] && grep -qsE '^DATABASE_URL=.+' .env; then
    log "Database migrations"
    .venv/bin/alembic upgrade head
fi

# --- frontend ----------------------------------------------------------------
log "Frontend build ($SITE_URL)"
cd "$REPO_DIR/frontend"
bun install --frozen-lockfile
VITE_ASPIRE_API_URL="$SITE_URL" bun run build

# An empty result means the build fell back to http://localhost:8000 and the
# deployed app would call the visitor's own machine. Catch it here, before the
# bundle is published, so the previous one keeps serving.
if ! grep -qrF -- "$SITE_URL" dist/client/assets/; then
    echo "ERROR: $SITE_URL was not baked into the bundle; refusing to publish" >&2
    exit 1
fi

# --- publish -----------------------------------------------------------------
# nginx serves $WEB_ROOT/client, a symlink. Alternating between two slots means
# the swap is a single atomic rename, and the previous generation's hashed
# assets stay on disk — so a page a visitor loaded seconds before the deploy can
# still fetch the files its HTML references.
log "Publishing client assets"
mkdir -p "$WEB_ROOT"
case "$(readlink -f "$WEB_ROOT/client" 2>/dev/null || true)" in
    */client.a) slot=client.b ;;
    *)          slot=client.a ;;
esac
rm -rf "${WEB_ROOT:?}/$slot"
cp -a dist/client "$WEB_ROOT/$slot"
ln -sfn "$WEB_ROOT/$slot" "$WEB_ROOT/.client.swap"
mv -Tf "$WEB_ROOT/.client.swap" "$WEB_ROOT/client"

# --- restart -----------------------------------------------------------------
# The SSR process holds dist/server/server.js in memory from its last start, so
# it keeps rendering the *old* HTML until this line.
#
# aspire-worker is in this list because the retention job lives in it. Note the
# sudoers rule in /etc/sudoers.d/aspire-deploy matches the WHOLE command, so
# adding a unit here without updating that file makes the deploy fail closed.
log "Restarting services"
sudo -n systemctl restart aspire-api aspire-web aspire-worker

# --- verify ------------------------------------------------------------------
wait_for() {
    local url=$1 name=$2 i
    for i in $(seq 1 60); do
        if curl -fsS --max-time 5 "$url" >/dev/null 2>&1; then
            echo "$name is answering"
            return 0
        fi
        sleep 1
    done
    echo "ERROR: $name never came back on $url" >&2
    echo "  journalctl -u aspire-api -u aspire-web -n 50 --no-pager" >&2
    return 1
}

log "Health"
# The API's first boot after an ingest-invalidating change re-embeds the corpus,
# which is why this waits a full minute rather than a few seconds.
wait_for http://127.0.0.1:8000/health api
wait_for http://127.0.0.1:3000/ web

log "Deployed ${before:0:8} -> ${after:0:8}"
