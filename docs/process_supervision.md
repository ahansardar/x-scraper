# Process Supervision

This project deploys without Docker. A production host must keep two long-running Python processes alive:

- web/API/frontend: `python .\run_app.py --host 0.0.0.0 --port 8000`
- worker/outbox consumer: `python .\run_worker.py`

Run both from the repository root after migrations and preflight have passed. Set `XINGESTION_DATA_DIR` to persistent storage outside the checkout before registering services.

## Recommended Host Shape

Use a host process manager such as Windows Task Scheduler, NSSM, WinSW, or your platform supervisor. Configure both processes with:

- working directory: the repository root
- startup type: automatic
- restart policy: restart on failure
- environment file: `.env` beside `run_app.py`
- persistent storage: `XINGESTION_DATA_DIR`
- stdout/stderr capture to a host-managed log location
- app log files: `XINGESTION_LOG_DIR` or `XINGESTION_DATA_DIR\logs`

## Windows Task Scheduler

Create one task for the web process and one task for the worker. Use "At startup" or "At log on" triggers depending on the host policy. Set "Start in" to the repository root.

Web action:

```powershell
python.exe F:\x-scraper\run_app.py --host 0.0.0.0 --port 8000
```

Worker action:

```powershell
python.exe F:\x-scraper\run_worker.py
```

Enable restart on failure in the task settings. If the host requires a virtual environment, point the action to that environment's `python.exe`.

## NSSM

NSSM can run each command as a Windows service.

```powershell
nssm install xingestion-web python.exe
nssm set xingestion-web AppDirectory F:\x-scraper
nssm set xingestion-web AppParameters F:\x-scraper\run_app.py --host 0.0.0.0 --port 8000
nssm set xingestion-web AppStdout F:\x-scraper-logs\web.log
nssm set xingestion-web AppStderr F:\x-scraper-logs\web.err.log
nssm set xingestion-web AppRestartDelay 5000

nssm install xingestion-worker python.exe
nssm set xingestion-worker AppDirectory F:\x-scraper
nssm set xingestion-worker AppParameters F:\x-scraper\run_worker.py
nssm set xingestion-worker AppStdout F:\x-scraper-logs\worker.log
nssm set xingestion-worker AppStderr F:\x-scraper-logs\worker.err.log
nssm set xingestion-worker AppRestartDelay 5000
```

Set machine-level environment variables or make sure `.env` is readable from `F:\x-scraper`.
Use `XINGESTION_LOG_DIR` when process stdout/stderr logs and application rotating logs should live in the same host-managed log root.

## Post-Start Verification

After starting the services:

```powershell
python .\run_preflight.py --base-url http://127.0.0.1:8000
python .\run_supervisor_check.py --base-url http://127.0.0.1:8000 --expect-processes --require-external-data-dir
python .\run_health_report.py --base-url http://127.0.0.1:8000
```

`run_supervisor_check.py` verifies JSON API liveness, current migrations, storage paths, outbox lag/depth, healthy session availability, release execution state, and optional process-table evidence for `run_app.py` and `run_worker.py`.

Use stricter queue thresholds when the deployment has a low-latency SLO:

```powershell
python .\run_supervisor_check.py --base-url http://127.0.0.1:8000 --expect-processes --max-outbox-lag-seconds 60 --max-unpublished-events 10
```

## Restart Checklist

After a host restart, confirm:

- web service is listening on the configured port
- worker service is running
- `run_supervisor_check.py --expect-processes` passes
- `run_health_report.py` writes a fresh report under `XINGESTION_DATA_DIR\reports`
- `GET /api/metrics` shows no unexpected outbox backlog
