import os
from collections import deque
from threading import Lock
from typing import Deque, Dict, List

from flask import Flask, jsonify, request

from monitor_core import (
    EmailAlerter,
    MonitorSettings,
    append_alert_log,
    append_csv_row,
    evaluate_critical,
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

app = Flask(__name__)
load_env_file()
settings = MonitorSettings.from_env()
alerter = EmailAlerter(settings)

api_token = os.getenv("API_AUTH_TOKEN", "").strip()
metrics_csv = os.path.join("data", "dashboard_metrics.csv")
alert_log = os.path.join("logs", "dashboard_alerts.log")

latest_by_machine: Dict[str, Dict[str, float]] = {}
history: Deque[Dict[str, float]] = deque(maxlen=2000)
state_lock = Lock()


def _is_authorized(req) -> bool:
    if not api_token:
        return True
    auth = req.headers.get("Authorization", "")
    return auth == f"Bearer {api_token}"


@app.post("/api/metrics")
def ingest_metrics():
    if not _is_authorized(request):
        return jsonify({"error": "Unauthorized"}), 401

    data = request.get_json(silent=True) or {}
    missing = [col for col in CSV_COLUMNS if col not in data]
    if missing:
        return jsonify({"error": f"Missing fields: {', '.join(missing)}"}), 400

    append_csv_row(metrics_csv, data, CSV_COLUMNS)

    machine = str(data["machine"])
    with state_lock:
        latest_by_machine[machine] = data
        history.append(data)

    reasons = evaluate_critical(data, settings)
    if reasons:
        msg = f"{machine} critical: " + "; ".join(reasons)
        append_alert_log(alert_log, msg)
        try:
            alerter.send_if_allowed(
                key=f"dashboard:{machine}",
                subject=f"Lab Monitor Critical - {machine}",
                body=f"{msg}\n\nMetrics: {data}",
            )
        except Exception as exc:
            append_alert_log(alert_log, f"Email send failed: {exc}")

    return jsonify({"status": "ok"}), 200


@app.get("/api/metrics/latest")
def latest_metrics():
    with state_lock:
        items: List[Dict[str, float]] = list(latest_by_machine.values())
    return jsonify({"machines": items, "count": len(items)})


@app.get("/")
def dashboard_view():
    with state_lock:
        machines = sorted(latest_by_machine.values(), key=lambda m: str(m["machine"]))

    rows = []
    for m in machines:
        reasons = evaluate_critical(m, settings)
        status = "CRITICAL" if reasons else "OK"
        status_color = "#b91c1c" if reasons else "#166534"
        rows.append(
            f"""
            <tr>
                <td>{m['machine']}</td>
                <td>{m['timestamp']}</td>
                <td>{m['cpu_percent']}%</td>
                <td>{m['ram_percent']}%</td>
                <td>{m['disk_used_percent']}%</td>
                <td>{m['disk_free_gb']} GB</td>
                <td style='font-weight:700;color:{status_color}'>{status}</td>
            </tr>
            """
        )

    if not rows:
        rows_html = "<tr><td colspan='7'>No data yet. Start one or more agents.</td></tr>"
    else:
        rows_html = "\n".join(rows)

    return f"""
    <!doctype html>
    <html>
    <head>
        <title>Lab Computer Health Monitor</title>
        <meta name='viewport' content='width=device-width, initial-scale=1'>
        <style>
            body {{ font-family: Segoe UI, Arial, sans-serif; margin: 24px; background: #f8fafc; color: #0f172a; }}
            .card {{ background: white; border-radius: 12px; box-shadow: 0 8px 24px rgba(0,0,0,.08); padding: 16px; overflow-x: auto; }}
            h1 {{ margin-top: 0; }}
            table {{ border-collapse: collapse; width: 100%; min-width: 800px; }}
            th, td {{ text-align: left; padding: 10px; border-bottom: 1px solid #e2e8f0; }}
            th {{ background: #f1f5f9; }}
            .meta {{ margin-bottom: 10px; color: #334155; }}
        </style>
    </head>
    <body>
        <h1>Lab Computer Health Monitor</h1>
        <div class='meta'>Monitored Machines: {len(machines)}</div>
        <div class='card'>
            <table>
                <thead>
                    <tr>
                        <th>Machine</th>
                        <th>Timestamp (UTC)</th>
                        <th>CPU</th>
                        <th>RAM</th>
                        <th>Disk Used</th>
                        <th>Disk Free</th>
                        <th>Status</th>
                    </tr>
                </thead>
                <tbody>
                    {rows_html}
                </tbody>
            </table>
        </div>
    </body>
    </html>
    """


if __name__ == "__main__":
    host = os.getenv("FLASK_HOST", "0.0.0.0")
    port = int(os.getenv("FLASK_PORT", "5000"))
    app.run(host=host, port=port, debug=False)
