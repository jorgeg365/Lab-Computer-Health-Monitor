import csv
import os
import smtplib
import socket
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from email.mime.text import MIMEText
from pathlib import Path
from typing import Dict, List

import psutil


def load_env_file(env_path: str = ".env") -> None:
    path = Path(env_path)
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def _env_bool(key: str, default: bool) -> bool:
    val = os.getenv(key)
    if val is None:
        return default
    return val.lower() in {"1", "true", "yes", "on"}


def _env_float(key: str, default: float) -> float:
    try:
        return float(os.getenv(key, str(default)))
    except ValueError:
        return default


def _env_int(key: str, default: int) -> int:
    try:
        return int(os.getenv(key, str(default)))
    except ValueError:
        return default


@dataclass
class MonitorSettings:
    interval_seconds: int
    cpu_critical_percent: float
    ram_critical_percent: float
    disk_min_free_gb: float
    email_enabled: bool
    smtp_host: str
    smtp_port: int
    smtp_user: str
    smtp_password: str
    alert_from: str
    alert_to: str
    email_cooldown_seconds: int

    @staticmethod
    def from_env() -> "MonitorSettings":
        return MonitorSettings(
            interval_seconds=_env_int("MONITOR_INTERVAL_SECONDS", 15),
            cpu_critical_percent=_env_float("CPU_CRITICAL_PERCENT", 90.0),
            ram_critical_percent=_env_float("RAM_CRITICAL_PERCENT", 90.0),
            disk_min_free_gb=_env_float("DISK_MIN_FREE_GB", 5.0),
            email_enabled=_env_bool("EMAIL_ALERTS_ENABLED", False),
            smtp_host=os.getenv("SMTP_HOST", ""),
            smtp_port=_env_int("SMTP_PORT", 587),
            smtp_user=os.getenv("SMTP_USER", ""),
            smtp_password=os.getenv("SMTP_PASSWORD", ""),
            alert_from=os.getenv("ALERT_FROM", ""),
            alert_to=os.getenv("ALERT_TO", ""),
            email_cooldown_seconds=_env_int("EMAIL_COOLDOWN_SECONDS", 600),
        )


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_machine_name() -> str:
    return os.getenv("AGENT_MACHINE_NAME") or os.getenv("COMPUTERNAME") or socket.gethostname()


def get_system_drive() -> str:
    if os.name == "nt":
        drive = os.getenv("SystemDrive", "C:")
        if not drive.endswith("\\"):
            drive += "\\"
        return drive
    return "/"


def collect_metrics(machine_name: str) -> Dict[str, float]:
    disk = psutil.disk_usage(get_system_drive())
    return {
        "timestamp": utc_now_iso(),
        "machine": machine_name,
        "cpu_percent": round(psutil.cpu_percent(interval=1), 2),
        "ram_percent": round(psutil.virtual_memory().percent, 2),
        "disk_used_percent": round(disk.percent, 2),
        "disk_free_gb": round(disk.free / (1024 ** 3), 2),
    }


def evaluate_critical(metrics: Dict[str, float], settings: MonitorSettings) -> List[str]:
    reasons: List[str] = []
    if float(metrics["cpu_percent"]) >= settings.cpu_critical_percent:
        reasons.append(f"High CPU: {metrics['cpu_percent']}%")
    if float(metrics["ram_percent"]) >= settings.ram_critical_percent:
        reasons.append(f"High RAM: {metrics['ram_percent']}%")
    if float(metrics["disk_free_gb"]) <= settings.disk_min_free_gb:
        reasons.append(f"Low Disk: {metrics['disk_free_gb']} GB free")
    return reasons


def ensure_parent_dir(file_path: str) -> None:
    Path(file_path).parent.mkdir(parents=True, exist_ok=True)


def append_csv_row(file_path: str, row: Dict[str, float], columns: List[str]) -> None:
    ensure_parent_dir(file_path)
    exists = Path(file_path).exists()
    with open(file_path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        if not exists:
            writer.writeheader()
        writer.writerow(row)


def append_alert_log(file_path: str, message: str) -> None:
    ensure_parent_dir(file_path)
    with open(file_path, "a", encoding="utf-8") as f:
        f.write(f"{utc_now_iso()} | {message}\n")


class EmailAlerter:
    def __init__(self, settings: MonitorSettings):
        self.settings = settings
        self._last_sent: Dict[str, float] = {}
        self._lock = threading.Lock()

    def send_if_allowed(self, key: str, subject: str, body: str) -> bool:
        if not self.settings.email_enabled:
            return False
        if not all([
            self.settings.smtp_host,
            self.settings.alert_from,
            self.settings.alert_to,
        ]):
            return False

        now_ts = datetime.now(timezone.utc).timestamp()
        with self._lock:
            last_ts = self._last_sent.get(key)
            if last_ts and (now_ts - last_ts) < self.settings.email_cooldown_seconds:
                return False

        msg = MIMEText(body)
        msg["Subject"] = subject
        msg["From"] = self.settings.alert_from
        msg["To"] = self.settings.alert_to

        with smtplib.SMTP(self.settings.smtp_host, self.settings.smtp_port, timeout=20) as server:
            server.starttls()
            if self.settings.smtp_user:
                server.login(self.settings.smtp_user, self.settings.smtp_password)
            server.sendmail(self.settings.alert_from, [self.settings.alert_to], msg.as_string())

        with self._lock:
            self._last_sent[key] = now_ts
        return True
