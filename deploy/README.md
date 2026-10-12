# Deploying InsightFlow (owner-only): runbook and templates

**Status: templates only. Nothing has been deployed, provisioned, or registered.** These files describe how InsightFlow is meant to run on one Linux server (planned: an Oracle Cloud Always Free VM with Ubuntu 24.04) for **one owner**. Every placeholder must be replaced and every check in [Before any external access](#before-any-external-access) must pass before the site is reachable from the internet.

**What this setup is, and is not**

- **Owner-only.** nginx asks for a username and password on every path (the frontend and the API). Only the owner gets credentials. There is no public sign-up.
- **Cross-site requests are refused.** Browsers send the sign-in automatically, even with a form another website submits, so requests that change something are refused when they come from another site (see [Cross-site protection](#cross-site-protection)).
- **Not per-user authorization.** The sign-in happens at the reverse proxy. InsightFlow itself has no accounts: anyone who has the credentials can see, analyze, and delete **every** saved dataset. The dataset library stays shared.
- **Not for public or untrusted users.** Adding real accounts with per-user datasets is separate, unimplemented work (see [Remaining blockers](#remaining-blockers-before-any-public-deployment)).
- **No guarantees about the provider.** Free-tier terms, prices, quotas, and the availability of a free host name were checked on 2026-10-13 and can change at any time. Check them again before you rely on them.

| File | What it is |
| --- | --- |
| [`insightflow.env.example`](insightflow.env.example) | The app's settings on the server (no secrets) |
| [`systemd/insightflow.service`](systemd/insightflow.service) | Runs Uvicorn (one worker) on `127.0.0.1:8000` with a hardened sandbox |
| [`systemd/insightflow-backup.service`](systemd/insightflow-backup.service), [`.timer`](systemd/insightflow-backup.timer) | Daily backup of the library, then a retention preview |
| [`systemd/insightflow-backup-failed.service`](systemd/insightflow-backup-failed.service) | Records a failed backup for the login message |
| [`motd/90-insightflow`](motd/90-insightflow) | Shows backup failures, a stopped API, and a full backup disk at SSH login |
| [`nginx/insightflow-http.conf`](nginx/insightflow-http.conf) | Port 80: Let's Encrypt check and redirect to HTTPS |
| [`nginx/insightflow-https.conf`](nginx/insightflow-https.conf) | Port 443: sign-in, limits, the built frontend, `/api` to Uvicorn |

## Architecture

```
Browser ──HTTPS──► nginx (ports 80 and 443 only)
                   ├─ owner sign-in on every path (auth_basic)
                   ├─ body size, request rate, and connection limits; timeouts; security headers
                   ├─ /                → /opt/insightflow/current/frontend/dist   (static files)
                   └─ /api/*           → http://127.0.0.1:8000                     (readiness: server only)
                                          │
                         systemd: insightflow.service — Uvicorn, 1 worker, user "insightflow"
                         ALLOWED_HOSTS check, upload limit, DuckDB limits (as in development)
                                          │
                         DATA_DIR=/var/lib/insightflow/library   (on a separate data volume)
                           ├─ insightflow.db         SQLite: datasets, analysis history, AI summary records
                           └─ uploads/<sha256>.csv   stored files
                                          │ daily, insightflow-backup.timer
                         /var/backups/insightflow/insightflow-backup-<UTC time>/   (+ copies on the owner's computer)
```

- **One Uvicorn worker.** The "one AI summary at a time" guard lives in the process (audit F14), and each worker needs its own memory for analyses (F7). SQLite on a local disk handles one writer at a time.
- **Port 8000 is never public.** Uvicorn listens on `127.0.0.1` only, and the cloud firewall allows only 80, 443, and SSH from the owner's address.
- **Ollama stays off** (`INSIGHTS_NARRATOR=none`). The local AI summary needs Ollama on the same machine; it is not set up on the server.
- **Persistent data** lives under `/var/lib/insightflow`, a separately mounted volume, so it survives replacing the VM or its boot disk. The library is the folder `library/` inside it, so a restore can move the old library aside (a mount point cannot be renamed).

## Placeholders to replace

| Placeholder | Where | Replace with |
| --- | --- | --- |
| `INSIGHTFLOW_HOSTNAME` | `insightflow.env.example`, both nginx files | The verified host name, for example `myname.duckdns.org` (see [Host name](#host-name)). The app refuses to start while the placeholder is in `ALLOWED_HOSTS`. |
| `owner` | The password file command below | The owner's sign-in name |
| `OWNER_IP` | Cloud firewall rule for SSH | The owner's public IP address (`/32`) |
| `<commit>` | Deploy commands | The full Git commit being deployed |

Paths (`/opt/insightflow`, `/var/lib/insightflow`, `/var/backups/insightflow`, `/etc/insightflow`) are fixed in the templates. If you change one, change it everywhere.

## Host name

A certificate needs a host name. **Nothing has been registered.** Options checked on 2026-10-13:

| Option | Verified facts | Suitability |
| --- | --- | --- |
| **Duck DNS** (`<name>.duckdns.org`) | Free, run by two engineers and funded by donations ([about](https://www.duckdns.org/about.jsp)). Updates over HTTPS, with IPv4/IPv6 and TXT records ([spec](https://www.duckdns.org/spec.jsp)). `duckdns.org` is on the [Public Suffix List](https://publicsuffix.org/list/public_suffix_list.dat), so each subdomain has its own [Let's Encrypt limit](https://letsencrypt.org/docs/rate-limits/) of 50 certificates per 7 days. The [terms](https://www.duckdns.org/tac.jsp) offer no uptime warranty and say an account can be suspended "at any time with or without notice". | Fine for an owner-only hobby deployment. No service guarantee: if Duck DNS is down or drops the name, the site is unreachable until the host name changes. |
| **deSEC** (`<name>.dedyn.io`) | `dedyn.io` is on the Public Suffix List (submitted by deSEC). Its [docs](https://desec.readthedocs.io/en/latest/) describe certbot integration. Price, operator, and per-account limits were **not** confirmed from its own pages. | Possible alternative; verify before use. |
| **Your own domain** | Not priced or checked. | The most durable option, at a yearly cost. |

Verify availability and terms again on the day you register. Never commit the Duck DNS token. It is a secret (it can repoint the name).

## Server setup (once)

These commands assume a fresh Ubuntu 24.04 VM, a data volume mounted at `/var/lib/insightflow`, and an SSH user with `sudo`. They are a checklist, not a script. Read each one before running it.

1. **Firewall.** In the cloud console, allow inbound TCP 443 and 80 from anywhere, and 22 only from `OWNER_IP/32`. Nothing else, and **never 8000**. Also check the VM's own firewall (`sudo iptables -L INPUT -n`). Ubuntu images on some clouds, Oracle's among them by common report (not verified here), ship rules that also need 80/443 opened on the host.
2. **SSH.** Key-only sign-in: in `/etc/ssh/sshd_config`, set `PasswordAuthentication no` and `PermitRootLogin no`, then `sudo systemctl reload ssh`. Keep the private key on the owner's computer only.
3. **Packages:** `sudo apt update && sudo apt install nginx certbot python3.12-venv sqlite3`, and turn on automatic security updates: `sudo apt install unattended-upgrades`.
4. **User and folders:**
   ```bash
   sudo useradd --system --home-dir /nonexistent --shell /usr/sbin/nologin insightflow
   # The data volume's mount point too: a restore creates its working folder next to library/.
   sudo install -d -o insightflow -g insightflow -m 0700 /var/lib/insightflow /var/lib/insightflow/library /var/backups/insightflow
   # Failure notices for the login message: written by root, cleared by the backup job.
   sudo install -d -o insightflow -g insightflow -m 0755 /var/lib/insightflow-status
   sudo install -d -o root -g root -m 0755 /opt/insightflow/releases /var/www/letsencrypt
   sudo install -d -o root -g insightflow -m 0750 /etc/insightflow
   ```
   Keep `/var/backups/insightflow` on a different disk from the data volume and from the system disk if you can: full backups add up (see [Disk space and retention](#disk-space-and-retention)). Either way, copy backups off the server (see [Backups](#backups)).
5. **Settings:** copy `insightflow.env.example` to `/etc/insightflow/insightflow.env`, replace `INSIGHTFLOW_HOSTNAME`, then `sudo chown root:insightflow /etc/insightflow/insightflow.env && sudo chmod 0640 /etc/insightflow/insightflow.env`.
6. **First release:** follow [Deploying a release](#deploying-a-release), steps 1 to 4, then step 5a ([First release only](#5a-first-release-only)). This creates `/opt/insightflow/current`, which every service below uses. There is nothing to back up yet.
7. **Services:** copy the four files in `systemd/` to `/etc/systemd/system/`, then run `sudo systemctl daemon-reload && sudo systemctl enable --now insightflow`. Check readiness ([Health checks](#health-checks)): this first request creates the empty library database.
8. **Backups and alerts:** `sudo systemctl enable --now insightflow-backup.timer`, then `sudo systemctl start insightflow-backup.service` and check that it succeeded (`systemctl status insightflow-backup.service`). Install the login message: `sudo install -o root -g root -m 0755 motd/90-insightflow /etc/update-motd.d/90-insightflow`. See [Alerts](#alerts).

### HTTPS and sign-in

1. **Owner password.** Generate a long random password (20+ characters) in a password manager. Then, on the server (it prompts for the password, so it never appears in the shell history):
   ```bash
   printf 'owner:%s\n' "$(openssl passwd -6)" | sudo tee /etc/nginx/insightflow.htpasswd > /dev/null
   sudo chown root:www-data /etc/nginx/insightflow.htpasswd && sudo chmod 0640 /etc/nginx/insightflow.htpasswd
   ```
   `openssl passwd -6` is SHA-512-crypt, which nginx reads with the system's `crypt()`. The rate limit slows guessing, but the password's length is what protects it.
2. **HTTP first.** Copy `nginx/insightflow-http.conf` to `/etc/nginx/sites-available/`, replace `INSIGHTFLOW_HOSTNAME`, and link it into `sites-enabled/`. Disable Ubuntu's own default site (`sudo rm /etc/nginx/sites-enabled/default` removes only the link; the original stays in `sites-available/`). Then run `sudo nginx -t && sudo systemctl reload nginx`.
3. **Certificate:**
   ```bash
   sudo certbot certonly --webroot -w /var/www/letsencrypt -d INSIGHTFLOW_HOSTNAME \
        --deploy-hook "systemctl reload nginx"
   ```
   Renewal runs automatically (`systemctl list-timers | grep certbot`) through the same port-80 location.
4. **HTTPS.** Do the same with `nginx/insightflow-https.conf`, then `sudo nginx -t && sudo systemctl reload nginx`.
5. If you raise `MAX_UPLOAD_MB`, raise `client_max_body_size` in `insightflow-https.conf` to about 1 MB more.

## Environment variables

Set in `/etc/insightflow/insightflow.env`. None of them is a secret, and none of them belongs in Git with real values.

| Variable | Server value | Notes |
| --- | --- | --- |
| `APP_ENV` | `production` | Turns off `/docs`, `/redoc`, `/openapi.json`, and requires `ALLOWED_HOSTS`. |
| `ALLOWED_HOSTS` | `INSIGHTFLOW_HOSTNAME,127.0.0.1` | Host headers the API answers; any other gets 400. No wildcards in production. `127.0.0.1` is for checks run on the server. |
| `DATA_DIR` | `/var/lib/insightflow/library` | The library (database + stored files). |
| `MAX_UPLOAD_MB` | `10` | Keep nginx's `client_max_body_size` about 1 MB above it. |
| `DUCKDB_THREADS` | `2` | Per analysis. |
| `DUCKDB_MEMORY_LIMIT` | `1GB` | Per analysis; the systemd unit's `MemoryMax` caps the total. |
| `INSIGHTS_NARRATOR` | `none` | The AI summary stays off on the server. |
| `OLLAMA_URL`, `OLLAMA_MODEL`, `OLLAMA_TIMEOUT_SECONDS`, `GEMINI_API_KEY` | not set | Unused on the server. |

The real secrets live outside the app and outside Git: the nginx password file, the owner's SSH private key, and the Duck DNS token (if used).

## Deploying a release

On the owner's computer, from a clean checkout of the commit to deploy (`git status` shows nothing):

1. Run the checks in the main [README](../README.md#running-tests-and-checks), then build the frontend: `cd frontend; npm ci; npm run build; cd ..`
2. Package and copy (PowerShell; `tar` and `scp` are built into Windows):
   ```powershell
   git archive --format=tar.gz -o insightflow-<commit>.tar.gz <commit>
   tar -czf insightflow-dist-<commit>.tar.gz -C frontend dist
   scp insightflow-<commit>.tar.gz insightflow-dist-<commit>.tar.gz owner@INSIGHTFLOW_HOSTNAME:/tmp/
   ```

On the server:

3. Unpack into a new release folder and install the **runtime** dependencies only:
   ```bash
   C=<commit>; R=/opt/insightflow/releases/$C
   sudo mkdir "$R" && sudo tar -xzf /tmp/insightflow-$C.tar.gz -C "$R"
   sudo mkdir -p "$R/frontend" && sudo tar -xzf /tmp/insightflow-dist-$C.tar.gz -C "$R/frontend"
   sudo python3.12 -m venv "$R/backend/.venv"
   sudo "$R/backend/.venv/bin/pip" install --require-virtualenv -r "$R/backend/requirements.txt"
   ```
4. **Run the test suite on the server's Python 3.12** (this is the real 3.12 check), in a separate throwaway environment:
   ```bash
   python3.12 -m venv /tmp/insightflow-tests && /tmp/insightflow-tests/bin/pip install -r "$R/backend/requirements-dev.txt"
   (cd "$R/backend" && PYTHONDONTWRITEBYTECODE=1 /tmp/insightflow-tests/bin/python -m pytest -q -p no:cacheprovider)
   rm -rf /tmp/insightflow-tests
   ```
   The tests use temporary folders, never `/var/lib/insightflow`. Stop here if anything fails.

#### 5a. First release only

There is no previous release and no library yet, so there is nothing to back up. Create the `current` link, then continue with [Server setup](#server-setup-once), step 7:
```bash
test ! -e /opt/insightflow/current && sudo ln -s "$R" /opt/insightflow/current   # refuses if a release is already live
```

#### 5b. Every later release: back up, then switch

The previous release stays in place for rollback.
```bash
sudo systemctl start insightflow-backup.service          # waits for the backup; stop here if it fails
systemctl show -p Result insightflow-backup.service      # must say Result=success
sudo ln -sfn "$R" /opt/insightflow/current.new && sudo mv -T /opt/insightflow/current.new /opt/insightflow/current
sudo systemctl restart insightflow
```

6. Run [After every deployment](#after-every-deployment). Remove the files in `/tmp`. Keep the last two or three release folders for rollback; remove older ones with `sudo rm -r /opt/insightflow/releases/<old commit>` (never the one `current` points to: `readlink /opt/insightflow/current`).

### Rollback

**After a later release (5b):**
1. Point `current` back at the previous release and restart:
   ```bash
   sudo ln -sfn /opt/insightflow/releases/<previous commit> /opt/insightflow/current.new
   sudo mv -T /opt/insightflow/current.new /opt/insightflow/current && sudo systemctl restart insightflow
   ```
2. Check readiness. Migrations only move forward. If the new release added one, the old code reports `"The database schema is not up to date."` (503). Then restore the backup taken in step 5b (see [Restore](#restore)), with the previous release running. Changes made after that backup are not in it, but the newer library is kept aside, not deleted.

**After the first release (5a):** there is no earlier release to go back to. Stop the service (`sudo systemctl stop insightflow insightflow-backup.timer`), fix the problem, and deploy a corrected release with steps 1 to 4 and 5b. 5b's backup also covers anything saved meanwhile. Only if nothing worth keeping was saved, you may instead point the link at the corrected release directly (`sudo ln -sfn "$R" /opt/insightflow/current.new && sudo mv -T /opt/insightflow/current.new /opt/insightflow/current`).

## Health checks

| Check | Command (on the server) | Expected |
| --- | --- | --- |
| Liveness | `curl -fsS http://127.0.0.1:8000/api/health` | `200`, `"environment":"production"` |
| Readiness | `curl -fsS http://127.0.0.1:8000/api/health/ready` | `200`, `"status":"ready"`. `503` lists what failed (database, data folder); details are in `journalctl -u insightflow`. |
| Service | `systemctl status insightflow`, `journalctl -u insightflow -n 50` | `active (running)`, no errors |

Readiness is not reachable from outside (nginx answers 404). The server runs it locally.

## After every deployment

Run from the owner's computer (PowerShell: use `curl.exe`) unless marked "server".

- [ ] `curl.exe -sS -o NUL -w "%{http_code}" https://INSIGHTFLOW_HOSTNAME/` → `401` (sign-in required, nothing served)
- [ ] `curl.exe -sS -u owner https://INSIGHTFLOW_HOSTNAME/api/health` → `200`
- [ ] `curl.exe -sS -o NUL -w "%{http_code}" http://INSIGHTFLOW_HOSTNAME/` → `301` to HTTPS
- [ ] `curl.exe -sS -o NUL -w "%{http_code}" -u owner https://INSIGHTFLOW_HOSTNAME/api/health/ready` → `404`
- [ ] Port 8000 is closed from outside: `Test-NetConnection INSIGHTFLOW_HOSTNAME -Port 8000` → `TcpTestSucceeded : False`
- [ ] (server) Uvicorn listens on localhost only: `sudo ss -ltnp | grep 8000` shows `127.0.0.1:8000`
- [ ] (server) Unknown host names are refused: `curl -s -H "Host: evil.example" http://127.0.0.1:8000/api/health` → `Invalid host header`
- [ ] (server) API docs are off: `curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8000/docs` → `404`
- [ ] Cross-site requests are refused: `curl.exe -sS -o NUL -w "%{http_code}" -u owner -X DELETE -H "Origin: https://evil.example" https://INSIGHTFLOW_HOSTNAME/api/datasets/999999` → `403` (and the same with `-H "Sec-Fetch-Site: cross-site"` instead of `Origin`)
- [ ] (server) The app refuses them too, without nginx: `curl -s -X DELETE -H "Origin: https://evil.example" http://127.0.0.1:8000/api/datasets/999999` → `403` with "came from another website"
- [ ] Oversized upload is refused by nginx: a 12 MB file to `POST /api/uploads/csv` → `413`
- [ ] Rate limit works: about 100 quick requests to `/api/health` → some `429`
- [ ] In the browser: sign in, analyze `backend/tests/fixtures/sample_sales.csv`, save it, open it under **Saved datasets**
- [ ] (server) `sudo systemctl start insightflow-backup.service`, then `systemctl status insightflow-backup.service` → exit `0`

## Cross-site protection

The owner's browser sends the sign-in with **every** request to the site, including one that another website triggers (for example a hidden form that posts a file). So the sign-in alone does not stop another site from making the owner's browser upload, analyze, or delete. Two layers refuse such requests with `403`:

| Request | Result |
| --- | --- |
| `GET`, `HEAD`, `OPTIONS` | Always allowed: they change nothing, and browsers do not let another site read the answer. Links from other sites still open the app. |
| Any other method (`POST`, `DELETE`, ...) with `Sec-Fetch-Site: cross-site`, `same-site`, or an unknown value | Refused. `same-site` is refused too: on a shared domain such as `duckdns.org`, other people's subdomains count as "same site". |
| Any other method with an `Origin` that is not this site (`https://` + its host name), including `null` and malformed values | Refused |
| Any other method from the InsightFlow page itself (`Sec-Fetch-Site: same-origin`, matching `Origin`) | Allowed |
| Any other method **without** `Sec-Fetch-Site` and `Origin` | Allowed. Current browsers send at least one of them with any request another site can trigger, so these come from non-browser clients (curl, scripts) that have no stored credentials to misuse. The checks the server runs on itself are `GET`s. |

- **nginx** (`insightflow-https.conf`, maps at the top) applies this to `/api/` with the origin written in (`https://INSIGHTFLOW_HOSTNAME`).
- **The API** (`backend/app/api/cross_site.py`) applies the same rules to every request, and stays authoritative if the proxy configuration changes. It derives the allowed origin from the request's own scheme and its `Host` header, which the `ALLOWED_HOSTS` check has already approved. So it needs no extra setting, and in development the Vite page (`http://localhost:5180`) counts as the same origin.
- **They differ only in strictness:** nginx compares exact lower-case strings and refuses an explicitly written `:443`, while the API compares parsed origins. Anything nginx allows, the API allows.
- **Assumption:** the "browsers send `Origin` or `Sec-Fetch-Site`" rule holds for current Chrome, Edge, Firefox, and Safari. It was not tested in a browser here, and a very old browser might send neither.

## Backups

**What:** the whole library, which is `insightflow.db` (datasets, analysis history, AI summary records) and every dataset's stored CSV file. Made by `python -m app.storage.backup` (see its docstring for the format).

| | |
| --- | --- |
| **Destination** | `/var/backups/insightflow/insightflow-backup-<UTC time>/`, plus copies on the owner's computer. Remote (Object Storage) copies are **not set up**; that is a separate, later step. |
| **Schedule** | Daily at 03:30 Philippine time (`insightflow-backup.timer`), and before every deployment. |
| **Service state** | The app **may keep running.** The database is copied with SQLite's online backup API, which holds only committed data. Each stored file is re-hashed while copied. A file deleted between the two steps, or already missing or changed, is left out and listed in `manifest.json`. That run exits with code 2, a failure for systemd (see [Alerts](#alerts)). |
| **Checks** | `SHA256SUMS` covers every file (`sha256sum -c SHA256SUMS` works on Linux). `manifest.json` records the schema version, counts, and problems, and every value in it is type-checked when read. The database passes `PRAGMA integrity_check` and `foreign_key_check`. Each backup is checked once more before it gets its final name. Symbolic links and special files inside a backup are refused. |
| **Safety** | Reads the library read-only (the systemd unit also mounts it read-only) and never creates or changes it. Never overwrites a backup. Refuses to start without enough free space. Backups must be outside `DATA_DIR`. |
| **Retention** | See [Disk space and retention](#disk-space-and-retention). Keep a copy no older than a week on the owner's computer as well. |

Check a backup at any time: `sudo -u insightflow /opt/insightflow/current/backend/.venv/bin/python -m app.storage.backup verify /var/backups/insightflow/<backup folder>` (run from `/opt/insightflow/current/backend`).

**Exit codes** of `create`, `verify`, and `restore`:

| Code | Meaning |
| --- | --- |
| `0` | Done. Every file matches its checksum, and every dataset's stored file is included. |
| `2` | Done, but **incomplete**. The backup itself is intact (every file matches its checksum), but some datasets' stored files were already missing or changed when it was made, so they are not in it. Each one is listed as a `WARNING`. A restore brings those datasets back as **Missing or changed**. Fix the cause: [Repairing a dataset whose stored file is missing](#repairing-a-dataset-whose-stored-file-is-missing). |
| `1` | Failed. For `create`, nothing was written (for example not enough free space). For `verify`, the backup is not valid. For `restore`, nothing was restored. A malformed manifest is reported as an error naming the bad field, never as a crash. |

**What the checksums prove, and what they do not.** SHA-256 detects *accidental* damage: a failing disk, an interrupted copy, a stray edit. Every file is checked against it before it is trusted, and a restore copies only bytes that match the checksums it has just verified. The checksums do **not** prove who made a backup. Anyone who can write to a backup folder (root, the `insightflow` user, or someone who gets either) can change files *and* recompute `SHA256SUMS` and `manifest.json`, and `verify` will accept the result. Tamper resistance needs something the server cannot change:
- copies on storage the server cannot rewrite: the owner's own computer, offline media, or later write-once (object-lock) storage;
- or a signature made with a key that never lives on the server (for example `ssh-keygen -Y sign` on the owner's computer over each copied `SHA256SUMS`). This is not set up.

A simple check that needs no setup: when you copy a backup home, keep a note of `sha256sum SHA256SUMS`. If it ever differs, that backup was changed after you copied it.

**Copy to the owner's computer (weekly):**
```bash
# server: package one backup for your SSH user (backups are readable by "insightflow" only)
B=insightflow-backup-<UTC time>
sudo tar -C /var/backups/insightflow -czf /tmp/$B.tar.gz $B && sudo chown "$USER" /tmp/$B.tar.gz
```
```powershell
# owner's computer, then remove /tmp/$B.tar.gz on the server
scp owner@INSIGHTFLOW_HOSTNAME:/tmp/<backup folder>.tar.gz .
tar -xzf <backup folder>.tar.gz
backend\.venv\Scripts\python.exe -m app.storage.backup verify <backup folder>   # from the repository's backend folder
```
The copy holds your raw sales data. Store it on an encrypted disk, outside OneDrive or other synced folders unless you mean to sync it.

### Disk space and retention

**Each backup is a full copy** of the library (database + every stored file). Nothing is shared between backups. With the default policy, up to 26 copies exist: 14 days plus 12 months, often fewer, because the newest backups also count for their month. Example: a 500 MB library needs up to about 13 GB for backups. A full system disk can stop the server's other services too. So:
- `create` refuses to start unless the disk keeps 5% of its size free after the backup plus a 10% margin. That run fails (exit 1) and raises an [alert](#alerts) instead of filling the disk.
- The login message warns when the backup disk is 90% full.
- Check usage at any time: `du -sh /var/backups/insightflow; df -h /var/backups/insightflow`.

**Retention policy** (`python -m app.storage.backup prune`):

| Kept | Default |
| --- | --- |
| The newest backup of each of the most recent **days that have backups** | `--keep-daily 14` |
| The newest backup of each of the most recent **months** | `--keep-monthly 12` |
| The newest backup that verifies cleanly (complete, every checksum matching), even when it is older than both windows | always |
| Damaged backups (failing `verify`) newer than that one, kept for inspection and reported | always |

- **Incomplete backups** (valid, but a dataset's stored file was missing or changed) follow the windows like any other. So a file that stays missing does not stop retention: old incomplete backups outside the windows are deleted, while the last clean backup and the most recent valid backup are kept. The windows never pick a damaged backup in place of a valid one.
- The windows count days and months that **have** backups, not calendar time. If backups stop for a month, the last good ones are not aged out.
- **If no backup verifies cleanly, nothing is deleted** and prune fails, so the job fails and alerts. That happens when a file was already missing before the first backup: [repair the dataset](#repairing-a-dataset-whose-stored-file-is-missing), and the next backup is clean.
- Prune only touches folders named exactly `insightflow-backup-YYYYMMDDTHHMMSSZ`, unfinished `.insightflow-backup-...partial-...` folders older than a day (left by runs that were killed outright), and `...deleting-...` folders of an interrupted prune. Your own files and links in that folder are never touched.
- **One `prune --apply` at a time.** It takes a lock (`.insightflow-prune.lock` in the backup folder; the OS releases it when the process ends, so it never goes stale) and checks the clean backup again just before deleting. A second one exits 1 without deleting anything. Each deleted folder is first renamed to `.…deleting-…`, so an interrupted prune never leaves a broken folder under a backup's name; the next prune finishes it.
- **Limitations.** Backups and restores do not take the lock. They don't need it: a prune only deletes folders that existed when it planned, and a restore from a folder being deleted fails without restoring anything. Deleting a backup by hand is not guarded. On nights when the backup exits 2 (incomplete), systemd skips the `prune` line in the job, so while a dataset is broken, prune by hand (below) or repair it.

**Preview first.** The backup job runs `prune` after every successful backup **without `--apply`**, so it only writes the plan to the journal (`journalctl -u insightflow-backup`): `KEEP` lines with the reason, and `DELETE` lines. Nothing is deleted automatically until you choose to:
```bash
cd /opt/insightflow/current/backend
sudo -u insightflow .venv/bin/python -m app.storage.backup prune --dest /var/backups/insightflow              # preview
sudo -u insightflow .venv/bin/python -m app.storage.backup prune --dest /var/backups/insightflow --apply      # delete
```
When the previews look right, add `--apply` to the `prune` line in `/etc/systemd/system/insightflow-backup.service` (then `sudo systemctl daemon-reload`), so old backups are removed daily. Until then, remove them yourself, or the disk check will eventually stop new backups.

### Repairing a dataset whose stored file is missing

**Signs:**
- the backup job fails with exit code `2` and a `WARNING: Dataset <id>: its stored file <sha256>.csv is missing` (or `changed on disk`);
- the dataset page shows **Missing or changed**;
- an analysis of that dataset is refused with `409`.

The page's badge checks only that the file exists with the right size, so a file *changed* without changing its size shows up only in the backup warning or the `409`. Every other dataset and all history are unaffected.

**1. Find the affected datasets** (read-only; the app can keep running):
```bash
# the newest backup's warnings name them:
cd /opt/insightflow/current/backend
sudo -u insightflow .venv/bin/python -m app.storage.backup verify \
     "$(sudo -u insightflow sh -c 'ls -d /var/backups/insightflow/insightflow-backup-* | tail -n 1')"   # the glob must expand as insightflow
# or check every stored file against its hash directly:
sudo -u insightflow sh -c 'cd /var/lib/insightflow/library && sqlite3 -readonly insightflow.db "SELECT id, sha256, filename FROM datasets ORDER BY id" |
  while IFS="|" read -r id sha name; do
    actual=$(sha256sum "uploads/$sha.csv" 2>/dev/null | cut -d" " -f1)
    if [ -z "$actual" ]; then echo "dataset $id ($name): stored file missing ($sha)";
    elif [ "$actual" != "$sha" ]; then echo "dataset $id ($name): stored file changed ($sha)"; fi
  done'
```
Note each dataset's id and SHA-256. The full hash is also in `GET /api/datasets/<id>` (`sha256`), and shown when you hover the shortened hash on its page.

**2a. Put the original file back: keeps the dataset and its whole analysis history.** The stored file is named after the SHA-256 of its exact bytes, so only the identical original fits. **Re-uploading it through the page does not repair it**: the app recognizes the content as already saved and leaves the missing file missing. Instead:
```bash
SHA=<the dataset's sha256>; LIB=/var/lib/insightflow/library
# The original bytes: your own copy of that CSV, or a clean backup's copy, which its SHA256SUMS already covers:
#   /var/backups/insightflow/<an older backup>/uploads/$SHA.csv
SRC=<path to that file>
sudo sha256sum "$SRC"        # must print exactly $SHA. If not, it is not the same file: stop and use 2b.
# Only if a *changed* file is present: move it aside, never delete it.
sudo -u insightflow mkdir -p /var/lib/insightflow/quarantine
sudo -u insightflow mv "$LIB/uploads/$SHA.csv" "/var/lib/insightflow/quarantine/$SHA.csv.changed-$(date -u +%Y%m%dT%H%M%SZ)"
# Copy under a temporary name, then rename, so the app never sees half a file. Owned by the service user.
sudo install -o insightflow -g insightflow -m 0600 "$SRC" "$LIB/uploads/.$SHA.csv.repair"
sudo -u insightflow mv "$LIB/uploads/.$SHA.csv.repair" "$LIB/uploads/$SHA.csv"
```
The service can keep running: the app re-checks the hash on every read. Then open the dataset page (the badge shows the file as stored) and run any analysis, which re-hashes the file.

**2b. No copy of the original anywhere: delete the dataset.** On its page, **Delete dataset**. That removes the dataset and its analysis history from the live library. Older backups still hold them, and the dataset can be restored from one into a scratch folder if you ever need to look. If you find the file later, save it again as a new dataset.

**3. Confirm:** `sudo systemctl start insightflow-backup.service`, then `systemctl show -p Result insightflow-backup.service` must say `Result=success`. That clears the login notice. From now on backups are complete again, and `prune --apply` removes old incomplete backups outside the windows.

### Alerts

There is **no email or push notification**: it would need a mail server or an outside service, which this deployment does not include. Failures are made visible on the server instead:

| What | Where you see it |
| --- | --- |
| A backup fails: error, exit code 2 (incomplete), not enough space, prune refusing, or the 45-minute timeout | **The SSH login message** (`motd/90-insightflow`): `*** InsightFlow: the last backup FAILED (<time>)`. The notice stays until a backup succeeds. Also `systemctl --failed`, `journalctl -u insightflow-backup -n 50`, and `journalctl -p err -t insightflow-backup`. |
| Backups stopped altogether (timer disabled, server off at the time, ...) | The login message: `no backup in the last 2 days`. Also `systemctl list-timers insightflow-backup.timer`. |
| The API is down | The login message, and `systemctl status insightflow` |
| The backup disk is 90% full | The login message |

**Timeout.** A backup of a small library takes seconds. The job is stopped after 45 minutes (`TimeoutStartSec`), which means something is stuck, for example a database lock that is never released.
- On `SIGTERM` the job removes its unfinished folder and exits.
- If it does not stop within 60 seconds it is killed. That can leave an unfinished `.partial-` folder, which never gets a final backup name and which prune removes a day later.
- The live library is only read, so stopping the job cannot damage it.
- A long SQLite wait may not react to `SIGTERM` until the wait ends. That is why systemd's kill after 60 seconds exists.

This only helps if you sign in. Make a habit of `ssh` to the server at least weekly, which you do anyway to copy a backup home.

### Restore

A restore never writes over a library. It checks the backup first, then fills a **new or empty** folder. The current library is moved aside, never deleted.

```bash
sudo systemctl stop insightflow
sudo mv /var/lib/insightflow/library /var/lib/insightflow/library.before-restore-$(date -u +%Y%m%dT%H%M%SZ)
cd /opt/insightflow/current/backend
sudo -u insightflow .venv/bin/python -m app.storage.backup restore /var/backups/insightflow/<backup folder> \
     --target /var/lib/insightflow/library
sudo systemctl start insightflow
curl -fsS http://127.0.0.1:8000/api/health/ready
```

- **Requires the service to be stopped.** It is the only step that does.
- **Integrity:** the backup is verified, then every file is copied from a fresh read that must match the checksum just verified. A backup changed or swapped in between is refused, and nothing is restored. Links and special files inside a backup are refused.
- A backup made by a newer InsightFlow (higher schema version) is refused. An older one is upgraded by the app's migrations when it starts.
- Datasets whose files were missing at backup time come back with **Missing or changed**, as they were. The restore then exits with code `2` (incomplete) and lists them.
- **Practise it** every month into a scratch folder (`--target /tmp/restore-test`, then remove it). The automated tests cover the same path (`backend/tests/test_backup.py`).

## Before any external access

All of these must be true before the host name points at the server:

- [ ] HTTPS with a valid certificate; HTTP only redirects
- [ ] Owner-only sign-in on every path (`401` without it); strong password
- [ ] Cross-site requests refused by nginx and by the app (`403` in the checks)
- [ ] `client_max_body_size`, request rate, and connection limits active (`413`, `429` seen in the checks)
- [ ] Cloud firewall: 443/80 open, 22 only from `OWNER_IP`, **8000 closed**; Uvicorn on `127.0.0.1` only
- [ ] SSH key-only, no root login
- [ ] `APP_ENV=production` with a real `ALLOWED_HOSTS`; `INSIGHTS_NARRATOR=none`
- [ ] Backups running, one verified, and one test restore done; the login message installed; the backup disk checked
- [ ] Automatic security updates on

## Remaining blockers before any public deployment

This setup is for the owner only. Before anyone else, or the public, gets access:

- **Per-user authorization (audit F5).** Accounts in the app, datasets owned by users, every query scoped to its owner, sessions with CSRF protection. Today any signed-in person shares one library and can delete everything.
- **Heavy work slows other requests (F3, F7).** CSV parsing and profiling are pure Python. One large upload is felt by everyone else, and one upload can use several GB at peak.
- **No server-side cancellation.** The page gives up after 120 s; the server keeps computing.
- **History grows without limit (F10)** and there is no storage quota.
- **Data at rest** is not encrypted by the app (F15). It relies on the disk and the host's access control.
- **Real-model AI summaries** are not validated (F14, narration off on the server).

See [docs/PRODUCTION_READINESS_AUDIT.md](../docs/PRODUCTION_READINESS_AUDIT.md) for the full list.
