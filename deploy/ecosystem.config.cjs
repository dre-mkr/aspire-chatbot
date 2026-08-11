/**
 * pm2 process definitions for ASPIRE.
 *
 *   pm2 start deploy/ecosystem.config.cjs
 *   pm2 save                 # <- without this, nothing comes back after a reboot
 *   pm2 startup              # prints a command to run once, as root
 *
 * .cjs, not .js: the frontend package.json sets "type": "module", and pm2 loads
 * this file with require().
 */

const ROOT = "/root/aspire";

module.exports = {
  apps: [
    {
      name: "aspire-api",
      cwd: `${ROOT}/backend`,

      // The venv's uvicorn is an executable with its own shebang, so pm2 must
      // exec it directly instead of handing it to node.
      script: ".venv/bin/uvicorn",
      interpreter: "none",
      args: [
        "app.main:app",
        "--host 127.0.0.1",
        "--port 8000",
        // Load-bearing. See the note below.
        "--workers 1",
        "--proxy-headers",
        "--forwarded-allow-ips 127.0.0.1",
      ].join(" "),

      // NEVER raise these two for the API.
      //
      // Conversation history itself is safe across processes now — it is
      // langgraph's `AsyncPostgresSaver` in Neon (app/graph/checkpointer.py).
      // What is not safe is everything still held in process memory:
      //
      //   - the rate limiter, a module-level dict of sliding windows
      //     (app/limits.py: `SlidingWindowLimiter._hits`). Its docstring records
      //     the decision that a per-process window IS the whole service's
      //     window — true only while there is one process. A second worker
      //     silently doubles every limit on the endpoints that spend model
      //     credits.
      //   - the voice limiter in app/voice/router.py, same shape.
      //   - game state (app/games/store.py), which is per-process by design.
      //
      // Scaling past one process means moving those to Valkey and making them
      // fail closed FIRST. Until then, add CPU rather than workers.
      instances: 1,
      exec_mode: "fork",

      // The backend reads backend/.env itself, by absolute path, so it does not
      // matter what cwd or env pm2 hands it. Do not duplicate secrets here.
      env: { PYTHONUNBUFFERED: "1" },

      max_restarts: 10,
      restart_delay: 3000,
      // A cold start ingests the knowledge base if the vector store is empty,
      // which is slow. Do not let pm2 call that a failed boot.
      min_uptime: "60s",
      kill_timeout: 10000,
    },

    {
      // The background worker. This is what enforces the 180-day deletion
      // commitment in backend/PRIVACY.md: app/jobs.py registers
      // `cron(retention_job, hour=3, minute=15)` and nothing else runs it.
      //
      // It was missing from both this file and the systemd units, so the cron
      // had never fired -- the audit found identities eight months past the
      // retention window still holding conversations. It is not optional and it
      // is not tied to MEMORY_WINDOW_ENABLED; that flag only affects the
      // summarisation job that shares this worker.
      name: "aspire-worker",
      cwd: `${ROOT}/backend`,

      // Same reasoning as uvicorn above: the venv's arq has its own shebang.
      script: ".venv/bin/arq",
      interpreter: "none",
      args: "app.jobs.WorkerSettings",

      // One is enough, and unlike the API this is a preference rather than a
      // constraint: arq coordinates through Valkey, so a cron job is claimed by
      // exactly one worker however many are running.
      instances: 1,
      exec_mode: "fork",

      env: { PYTHONUNBUFFERED: "1" },

      max_restarts: 10,
      restart_delay: 10000,
      min_uptime: "60s",
      kill_timeout: 10000,
    },

    {
      name: "aspire-web",
      cwd: `${ROOT}/frontend`,
      script: "server.mjs",

      // Unlike the API, this tier is stateless — SSR holds nothing between
      // requests — so cluster mode is safe here if you want the extra cores.
      // Set instances to a number or "max" and exec_mode to "cluster".
      instances: 1,
      exec_mode: "fork",

      env: {
        NODE_ENV: "production",
        HOST: "127.0.0.1",
        PORT: "3000",

        // Do NOT add VITE_ASPIRE_API_URL here. Vite reads it at BUILD time and
        // writes the literal string into the client bundle; nothing reads it at
        // runtime. Setting it here looks like it works and silently does
        // nothing. It belongs on the build command.
      },

      max_restarts: 10,
      restart_delay: 3000,
      min_uptime: "20s",
    },
  ],
};
