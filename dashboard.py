import os
from collections import deque
from html import escape
from threading import Lock
from typing import Deque, Dict, List

from flask import Flask, abort, jsonify, request, send_file

from monitor_core import (
    EmailAlerter,
    MonitorSettings,
    append_alert_csv,
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
alert_csv = os.path.join("data", "dashboard_alerts.csv")

latest_by_machine: Dict[str, Dict[str, float]] = {}
history: Deque[Dict[str, float]] = deque(maxlen=2000)
critical_alerts: Deque[Dict[str, str]] = deque(maxlen=200)
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
        append_alert_csv(alert_csv, machine, reasons, data)
        alert_entry = {
            "timestamp": str(data["timestamp"]),
            "machine": machine,
            "severity": "CRITICAL",
            "reasons": "; ".join(reasons),
            "cpu_percent": str(data["cpu_percent"]),
            "ram_percent": str(data["ram_percent"]),
            "disk_free_gb": str(data["disk_free_gb"]),
        }
        with state_lock:
            critical_alerts.appendleft(alert_entry)
        try:
            alerter.send_if_allowed(
                key=f"dashboard:{machine}",
                subject=f"Lab Monitor Critical - {machine}",
                body=f"{msg}\n\nMetrics: {data}",
            )
        except Exception as exc:
            append_alert_log(alert_log, f"Email send failed: {exc}")

    return jsonify({"status": "ok"}), 200


@app.get("/export/metrics.csv")
def export_metrics_csv():
    if not os.path.exists(metrics_csv):
        abort(404, "No dashboard metrics CSV has been created yet.")
    return send_file(metrics_csv, as_attachment=True, download_name="dashboard_metrics.csv")


@app.get("/export/alerts.csv")
def export_alerts_csv():
    if not os.path.exists(alert_csv):
        abort(404, "No dashboard alerts CSV has been created yet.")
    return send_file(alert_csv, as_attachment=True, download_name="dashboard_alerts.csv")


@app.get("/api/metrics/latest")
def latest_metrics():
    with state_lock:
        items: List[Dict[str, float]] = list(latest_by_machine.values())
    return jsonify({"machines": items, "count": len(items)})


@app.get("/")
def dashboard_view():
    with state_lock:
        machines = sorted(latest_by_machine.values(), key=lambda m: str(m["machine"]))
        alerts = list(critical_alerts)[:20]

    rows = []
    critical_count = 0
    for m in machines:
        reasons = evaluate_critical(m, settings)
        status = "CRITICAL" if reasons else "OK"
        status_color = "#b91c1c" if reasons else "#166534"
        row_class = "critical-row" if reasons else ""
        reason_text = "; ".join(reasons) if reasons else "Healthy"
        if reasons:
            critical_count += 1
        machine_label = escape(str(m["machine"]))
        timestamp_label = escape(str(m["timestamp"]))
        reason_label = escape(reason_text)
        rows.append(
            f"""
            <tr class='{row_class}'>
                <td>{machine_label}</td>
                <td>{timestamp_label}</td>
                <td>{m['cpu_percent']}%</td>
                <td>{m['ram_percent']}%</td>
                <td>{m['disk_used_percent']}%</td>
                <td>{m['disk_free_gb']} GB</td>
                <td style='font-weight:700;color:{status_color}'>{status}</td>
                <td>{reason_label}</td>
            </tr>
            """
        )

    if not rows:
        rows_html = "<tr><td colspan='8'>No data yet. Start one or more agents.</td></tr>"
    else:
        rows_html = "\n".join(rows)

    alert_rows = []
    for alert in alerts:
        alert_rows.append(
            f"""
            <tr>
                <td>{escape(alert['timestamp'])}</td>
                <td>{escape(alert['machine'])}</td>
                <td>{escape(alert['severity'])}</td>
                <td>{escape(alert['reasons'])}</td>
                <td>{alert['cpu_percent']}%</td>
                <td>{alert['ram_percent']}%</td>
                <td>{alert['disk_free_gb']} GB</td>
            </tr>
            """
        )

    if not alert_rows:
        alert_rows_html = "<tr><td colspan='7'>No critical alerts yet.</td></tr>"
    else:
        alert_rows_html = "\n".join(alert_rows)

    health_class = "critical-banner" if critical_count else "ok-banner"
    health_text = (
        f"{critical_count} machine(s) need attention"
        if critical_count
        else "All reporting machines are healthy"
    )

    return f"""
    <!doctype html>
    <html>
    <head>
        <title>Lab Computer Health Monitor</title>
        <meta name='viewport' content='width=device-width, initial-scale=1'>
        <style>
            body {{ font-family: Segoe UI, Arial, sans-serif; margin: 24px; background: #f8fafc; color: #0f172a; }}
            .card {{ background: white; border-radius: 8px; box-shadow: 0 8px 24px rgba(0,0,0,.08); padding: 16px; overflow-x: auto; margin-bottom: 20px; }}
            .toolbar {{ display: flex; gap: 10px; flex-wrap: wrap; margin: 14px 0 18px; }}
            .button {{ display: inline-block; background: #0f172a; color: white; padding: 9px 12px; border-radius: 6px; text-decoration: none; font-weight: 700; }}
            .button.secondary {{ background: #334155; }}
            .banner {{ border-radius: 8px; padding: 14px 16px; font-weight: 800; margin: 12px 0; }}
            .critical-banner {{ background: #fee2e2; border: 1px solid #fca5a5; color: #991b1b; }}
            .ok-banner {{ background: #dcfce7; border: 1px solid #86efac; color: #14532d; }}
            .critical-row {{ background: #fff1f2; }}
            h1 {{ margin-top: 0; margin-bottom: 6px; }}
            h2 {{ margin: 0 0 12px; }}
            table {{ border-collapse: collapse; width: 100%; min-width: 800px; }}
            th, td {{ text-align: left; padding: 10px; border-bottom: 1px solid #e2e8f0; }}
            th {{ background: #f1f5f9; }}
            .meta {{ margin-bottom: 10px; color: #334155; }}
        </style>
    </head>
    <body>
        <h1>Lab Computer Health Monitor</h1>
        <div class='meta'>Monitored Machines: {len(machines)}</div>
        <div class='banner {health_class}'>{health_text}</div>
        <div class='toolbar'>
            <a class='button' href='/export/metrics.csv'>Export Metrics CSV</a>
            <a class='button secondary' href='/export/alerts.csv'>Export Critical Alerts CSV</a>
        </div>
        <div class='card'>
            <h2>Live Machine Health</h2>
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
                        <th>Alert Reason</th>
                    </tr>
                </thead>
                <tbody>
                    {rows_html}
                </tbody>
            </table>
        </div>
        <div class='card'>
            <h2>Recent Critical Alerts</h2>
            <table>
                <thead>
                    <tr>
                        <th>Timestamp (UTC)</th>
                        <th>Machine</th>
                        <th>Severity</th>
                        <th>Reason</th>
                        <th>CPU</th>
                        <th>RAM</th>
                        <th>Disk Free</th>
                    </tr>
                </thead>
                <tbody>
                    {alert_rows_html}
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
