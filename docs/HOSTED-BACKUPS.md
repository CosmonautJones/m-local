# Hosted backups pulled to the operator's machine

JacHammer offers no shell, database access or volume snapshots, so the app
produces its own backup and the operator's machine pulls it once a day. This is
a stopgap until a host with managed backups takes over (#45); it does not by
itself close the recovery gate in [BACKUP-RECOVERY.md](BACKUP-RECOVERY.md).

## What a backup holds

`download_backup` (in `services/operations.jac`, logic in
`services/hosted_backup.py`) answers only when the host has
`MLOCAL_BACKUP_TOKEN` set (40+ characters) and the request carries the same
token. It allows one backup every five minutes. Holding the app's mutation
lock, it returns one JSON document with:

- every application table in the graph database: rows as `row_to_json` text,
  read in one `REPEATABLE READ READ ONLY` transaction, plus column types,
  defaults, constraints, indexes and sequence positions;
- the private onboarding store (SQLite online-backup copies, integrity-checked),
  the original 32-byte onboarding key, the review-notice file and the photo
  ownership registry;
- uploaded photos (refused above 200 MB);
- a SHA-256 for every table, every file and the whole document.

Not included: host settings such as `JAC_SERVE_AUTH_SECRET` and the SMTP
password. Keep a copy of the project's settings with the passphrase (below);
without the original `JAC_SERVE_AUTH_SECRET` everyone has to sign in again.

The document contains account emails, sign-in records and the onboarding key.
The host never writes it to disk; it is sent once over HTTPS.

## Setting it up (once, from WSL)

```bash
python3 scripts/hosted-backup.py setup --url https://<app host> \
    --backup-dir "/mnt/c/Users/<you>/M-Local Backups" --show-token
jachammer env add 'MLOCAL_BACKUP_TOKEN=<printed token>' --name M-Local-Main
bash scripts/jachammer-deploy.sh   # applies the new setting
python3 scripts/hosted-backup.py pull
```

`setup` keeps the token and a random encryption passphrase in
`~/.mlocal-backup/` (mode 0600). **Copy the passphrase
(`~/.mlocal-backup/passphrase`) into a password manager**: the backups cannot be
read without it.

Copy the tool somewhere stable (`cp scripts/hosted-backup.py ~/.mlocal-backup/`)
and schedule the daily pull with Windows Task Scheduler. It runs at 03:37 and,
if the PC was off or asleep, as soon as it is next available:

```powershell
Register-ScheduledTask -TaskName 'M-Local daily backup' -Force `
  -Action (New-ScheduledTaskAction -Execute 'C:\Windows\System32\wsl.exe' `
    -Argument '-d Ubuntu -u <wsl user> -e bash -lc "python3 ~/.mlocal-backup/hosted-backup.py pull >> ~/.mlocal-backup/task.log 2>&1"') `
  -Trigger (New-ScheduledTaskTrigger -Daily -At 3:37am) `
  -Settings (New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -ExecutionTimeLimit (New-TimeSpan -Minutes 20))
```

Point the action at `wsl.exe` directly: a `.cmd` wrapper started by Task
Scheduler exited with code 1 without running anything on the test PC.

The task runs only while you are signed in to Windows. A missed day is caught
up at the next sign-in; check `backup.log` weekly.

## What `pull` does

1. Requests the snapshot with the token in the request body (never the URL).
2. Verifies the document, table and file checksums and that the onboarding key
   is present. Anything wrong stops here; older backups are kept.
3. Encrypts with gpg (AES-256, passphrase file) and writes
   `m-local-YYYYmmdd-HHMMSS.json.gpg`. Plaintext is never written.
4. Decrypts the stored copy and compares it with what was received.
5. Deletes encrypted copies older than 14 days, never the newest.
6. Appends one line to `~/.mlocal-backup/backup.log`.

Check that it ran: `tail ~/.mlocal-backup/backup.log`. Check a copy:
`python3 scripts/hosted-backup.py verify <file>`.

## Restoring

Into an **empty** PostgreSQL database plus empty directories:

```bash
python3 scripts/hosted-backup.py restore <file>.json.gpg \
    --psql "psql -h 127.0.0.1 -p 5432 -U jac -d restored" \
    --private-dir /srv/m-local/onboarding --photos-dir /app/assets/photos
```

Then start the **same source revision** at the **same entry path** the backup
prints (`/app/main.jac` on JacHammer; see "Preserve the application identity"
in [BACKUP-RECOVERY.md](BACKUP-RECOVERY.md)), with
`JAC_DB_URL` pointing at the restored database, `MLOCAL_ONBOARDING_DIR` at the
private directory and the original `JAC_SERVE_AUTH_SECRET`.

## Evidence, 2026-11-03

- `tests/onboarding/test_hosted_backup.py`: a disposable PostgreSQL 16 with
  jsonb, bytea, arrays, quoted text, a sequence, a unique constraint, a foreign
  key and an index; snapshot, encrypt, restore into a second database and
  re-snapshot. Every table hash, constraint, index and sequence matches; a
  tampered or keyless backup is refused.
- `services/operations.test.jac`: token gating, rate limit, checksums and the
  private store inside the snapshot.
- Local drill on the app's real schema: a running app with the hosted sample
  catalog and QA accounts (10 tables, 6,392 rows) was backed up through HTTP in
  1.4 s (514 KB encrypted), restored into a fresh PostgreSQL and booted at the
  same path. The restored app served the same 397 deals with the same stock, and
  an existing student's sign-in token returned the same account and claims.

- Hosted preview, `d49e108`: the first pull took 3 s (10 tables, 8,659 rows,
  799 KB encrypted, no plaintext emails in the file) and `verify` passed. The
  scheduled task then ran on its own and saved a second copy.

Not yet shown: a restore of a hosted backup onto another machine, and behavior
once photos or tables grow large.
