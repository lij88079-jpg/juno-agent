# Port Conflicts · Windows Handling (Juno Injection)

> Users often run QianKun AI and Totoro Campus together. Port conflicts are routine—identify the process, ask what to kill, then act.
> Never block the whole turn on long-running servers: background long jobs; verify port before claiming success.

---

<!-- INJECT:port-ops -->

## When a Port Is in Use (Required Order)

1. **Identify owner** (no random kills)
   ```text
   netstat -ano | findstr ":PORT"
   tasklist /FI "PID eq PID_NUMBER" /FO LIST
   ```
2. **Decide** (tell the user): kill stale process / change port / keep QianKun and run Totoro on another port
3. **After confirmation** `taskkill /PID … /F`, then `netstat` to confirm free

## Starting Frontend/Backend (No Fake "Started")

1. `run_shell` with **correct cwd** for `pnpm dev` / `npm run dev` / `tsx watch …` (background; capture `job_id`)
2. Wait 2–5s → `shell_job` for ready / Local: / listening in logs
3. `netstat` or `curl` to confirm port is listening
4. **Only after step 3** tell user ✅ started + URL
5. On failure: log highlights + port conflict options; do not spin the same command endlessly

### Forbidden
- Stopping at "port in use" without kill/switch options
- Claiming "frontend started" after background spawn without port check
- Blocking the turn on foreground `pnpm dev` until timeout unlock
- Killing QianKun's port without asking

### Verbal template
"5174 is QianKun Vite; 8787 has another process. Do you want: **① stop it and start Totoro ② keep both, new port for Totoro ③ kill only stale Totoro**?"

<!-- END:port-ops -->
