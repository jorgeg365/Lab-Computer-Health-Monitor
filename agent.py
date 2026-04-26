import os
import time

import requests

from monitor_core import (
    EmailAlerter,
    MonitorSettings,
    append_alert_log,
    append_csv_row,
    collect_metrics,
    evaluate_critical,
    get_machine_name,
    load_env_file,
)


CSV_COLUMNS = [
    "timestamp",
    "machine",
    "cpu_percent",
    "ram_percent",
    "disk_used_percent",
    "disk_free_gb",
]


def post_to_dashboard(payload: dict, dashboard_url: str, token: str) -> None:
    url = dashboard_url.rstrip("/") + "/api/metrics"
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    requests.post(url, json=payload, headers=headers, timeout=10).raise_for_status()


def main() -> None:
    load_env_file()
    settings = MonitorSettings.from_env()
    alerter = EmailAlerter(settings)

    machine = get_machine_name()
    dashboard_url = os.getenv("DASHBOARD_URL", "").strip()
    dashboard_token = os.getenv("DASHBOARD_AUTH_TOKEN", "").strip()

    local_csv = os.path.join("data", f"agent_metrics_{machine}.csv")
    local_alert_log = os.path.join("logs", f"agent_alerts_{machine}.log")

    print(f"Starting monitor agent for {machine}")
    if dashboard_url:
        print(f"Dashboard target: {dashboard_url}")

    while True:
        metrics = collect_metrics(machine)
        append_csv_row(local_csv, metrics, CSV_COLUMNS)

        reasons = evaluate_critical(metrics, settings)
        if reasons:
            msg = f"{machine} critical: " + "; ".join(reasons)
            append_alert_log(local_alert_log, msg)
            try:
                alerter.send_if_allowed(
                    key=f"agent:{machine}",
                    subject=f"Lab Monitor Alert - {machine}",
                    body=f"{msg}\n\nMetrics: {metrics}",
                )
            except Exception as exc:
                append_alert_log(local_alert_log, f"Email send failed: {exc}")

        if dashboard_url:
            try:
                post_to_dashboard(metrics, dashboard_url, dashboard_token)
            except Exception as exc:
                append_alert_log(local_alert_log, f"Dashboard post failed: {exc}")

        print(
            f"[{metrics['timestamp']}] {machine} "
            f"CPU={metrics['cpu_percent']}% RAM={metrics['ram_percent']}% "
            f"DiskFree={metrics['disk_free_gb']}GB"
        )
        time.sleep(settings.interval_seconds)


if __name__ == "__main__":
    main()
