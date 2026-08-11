# Logging

The deployment uses Python standard-library logging with rotating file handlers. No Docker or external log agent is required.

Default log directory:

```text
XINGESTION_DATA_DIR\logs
```

Default files:

- `web.log`
- `worker.log`
- `migrations.log`
- `preflight.log`
- `health-report.log`
- `supervisor-check.log`

## Environment

```env
XINGESTION_LOG_DIR=
XINGESTION_LOG_LEVEL=INFO
XINGESTION_LOG_MAX_BYTES=5242880
XINGESTION_LOG_BACKUP_COUNT=5
```

Leave `XINGESTION_LOG_DIR` blank to write under `XINGESTION_DATA_DIR\logs`. In production, keep `XINGESTION_DATA_DIR` on persistent storage so logs, SQLite state, raw evidence, and health reports survive restarts.

## Verification

Run an operator command and confirm a log file is created:

```powershell
python .\run_preflight.py
Get-ChildItem $env:XINGESTION_DATA_DIR\logs
```

When `XINGESTION_DATA_DIR` is unset locally, logs are written to:

```text
F:\x-scraper\data\logs
```

The process supervisor may also capture stdout/stderr separately. Keep those host-managed process logs outside the repository checkout.
