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

const ROOT = "/srv/aspire";

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
      // Conversation memory is a langgraph InMemorySaver and the voice rate
      // limiter is a process-local dict. Both live in the process. Run a second
      // instance and a follow-up question can land on the one that never saw
      // the first — the assistant loses the thread intermittently, which reads
      // as a model fault and is nearly impossible to reproduce on purpose.
      // Scaling past one process means moving both to Redis or Postgres first.
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
