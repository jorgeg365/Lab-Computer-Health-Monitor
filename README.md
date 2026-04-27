# Lab Computer Health Monitor

Monitor CPU, RAM, and disk usage across lab computers, trigger critical alerts, and export metrics to CSV.

## Features

- Tracks CPU %, RAM %, disk used %, and disk free GB using `psutil`
- Supports 20-50 machines by running a lightweight agent on each PC
- Central Flask dashboard for live health view (optional)
- Critical alerts for:
  - high CPU
  - high RAM
  - low disk free space
- Dashboard export buttons for:
  - all collected metrics as CSV
  - critical alerts as CSV
- Alert channels:
  - local log file
  - email via `smtplib` (optional)
- CSV export of all metrics

## Architecture

- `agent.py` runs on each lab PC and collects system stats.
- Agent writes local CSV/logs and can push metrics to dashboard API.
- `dashboard.py` receives metrics from many agents, stores CSV, and shows status page.

## Quick Start

1. Install dependencies:

```powershell
pip install -r requirements.txt
```

2. Copy env file:

```powershell
Copy-Item .env.example .env
```

3. Optional: edit `.env` for thresholds, SMTP, and auth token.

## Run Dashboard (optional)

```powershell
python dashboard.py
```

- Open: `http://localhost:5000`
- API endpoint for agents: `POST /api/metrics`
- Metrics CSV export: `http://localhost:5000/export/metrics.csv`
- Critical alerts CSV export: `http://localhost:5000/export/alerts.csv`

## Run Agent (each lab PC)

```powershell
python agent.py
```

## One-Click Start (Windows)

Use the included script to start both dashboard and agent right away:

```powershell
powershell -ExecutionPolicy Bypass -File .\Start-Monitor.ps1
```

Or just double-click this file in File Explorer:

```text
Start-Monitor.cmd
```

If you do not want to auto-activate `.venv`, run:

```powershell
powershell -ExecutionPolicy Bypass -File .\Start-Monitor.ps1 -NoVenv
```

The script writes PID files to `.runtime\dashboard.pid` and `.runtime\agent.pid` and avoids duplicate starts when those processes are already running.

## One-Click Stop (Windows)

To stop both dashboard and agent:

```powershell
powershell -ExecutionPolicy Bypass -File .\Stop-Monitor.ps1
```

Or double-click this file:

```text
Stop-Monitor.cmd
```

The agent will:

- collect system stats every `MONITOR_INTERVAL_SECONDS`
- append to `data/agent_metrics_<machine>.csv`
- write alerts to `logs/agent_alerts_<machine>.log`
- post stats to dashboard if `DASHBOARD_URL` is set

## Example: Scale to 20-50 PCs

1. Start `dashboard.py` on one central machine.
2. Set `DASHBOARD_URL` on each lab PC to the dashboard host.
3. Run `agent.py` as a background process/task on each PC.

## Data Output

- Central CSV: `data/dashboard_metrics.csv`
- Central critical alerts CSV: `data/dashboard_alerts.csv`
- Per-agent CSV: `data/agent_metrics_<machine>.csv`
- Per-agent critical alerts CSV: `data/agent_alerts_<machine>.csv`
- Dashboard alerts log: `logs/dashboard_alerts.log`
- Agent alerts log: `logs/agent_alerts_<machine>.log`

## Notes

- Disk check uses the system drive on Windows.
- Email alerts include a cooldown to prevent spam.
