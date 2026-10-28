"""IT Troubleshooting Toolkit: safe, read-only diagnostic checks."""
from __future__ import annotations

import argparse
import json
import platform
import socket
import subprocess
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass
class CheckResult:
    name: str
    status: str  # PASS, WARN, or FAIL
    summary: str
    details: dict[str, Any]


def check_system() -> CheckResult:
    """Collect basic OS and Python information without changing the system."""
    details = {
        "operating_system": platform.system(),
        "os_release": platform.release(),
        "architecture": platform.machine(),
        "python_version": platform.python_version(),
        "hostname": platform.node() or "unknown",
    }
    return CheckResult(
        name="system_info",
        status="PASS",
        summary=f"Collected system information for {details['operating_system']}.",
        details=details,
    )


def check_dns(host: str) -> CheckResult:
    """Resolve a hostname and report the returned IP addresses."""
    try:
        records = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
        addresses = sorted({record[4][0] for record in records})
        if not addresses:
            return CheckResult("dns", "WARN", f"No addresses returned for {host}.", {"host": host, "addresses": []})
        return CheckResult("dns", "PASS", f"Resolved {host} to {len(addresses)} address(es).", {"host": host, "addresses": addresses})
    except (socket.gaierror, OSError) as exc:
        return CheckResult("dns", "FAIL", f"Could not resolve {host}.", {"host": host, "error": str(exc)})


def check_tcp_port(host: str, port: int, timeout: float = 2.0) -> CheckResult:
    """Attempt a TCP connection to host:port; no data is sent."""
    if not 1 <= port <= 65535:
        return CheckResult("tcp_port", "FAIL", "Port must be between 1 and 65535.", {"host": host, "port": port})
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return CheckResult("tcp_port", "PASS", f"TCP connection to {host}:{port} succeeded.", {"host": host, "port": port, "timeout_seconds": timeout})
    except (socket.timeout, TimeoutError) as exc:
        return CheckResult("tcp_port", "WARN", f"Connection to {host}:{port} timed out.", {"host": host, "port": port, "timeout_seconds": timeout, "error": str(exc) or "timeout"})
    except OSError as exc:
        return CheckResult("tcp_port", "FAIL", f"Could not connect to {host}:{port}.", {"host": host, "port": port, "timeout_seconds": timeout, "error": str(exc)})


def check_ping(host: str, timeout_ms: int = 1500) -> CheckResult:
    """Run one platform-appropriate ping. ICMP may be blocked by networks."""
    if platform.system().lower() == "windows":
        command = ["ping", "-n", "1", "-w", str(timeout_ms), host]
    else:
        command = ["ping", "-c", "1", "-W", str(max(1, (timeout_ms + 999) // 1000)), host]
    try:
        completed = subprocess.run(command, capture_output=True, text=True, timeout=(timeout_ms / 1000) + 2, check=False)
        output = (completed.stdout + "\n" + completed.stderr).strip()
        if completed.returncode == 0:
            return CheckResult("ping", "PASS", f"Ping to {host} succeeded.", {"host": host, "return_code": completed.returncode, "output": output[-1500:]})
        return CheckResult("ping", "WARN", f"Ping to {host} failed or was blocked.", {"host": host, "return_code": completed.returncode, "output": output[-1500:]})
    except (OSError, subprocess.TimeoutExpired) as exc:
        return CheckResult("ping", "WARN", f"Ping could not be completed for {host}.", {"host": host, "error": str(exc)})


def build_report(host: str, ports: list[int], include_ping: bool = True) -> dict[str, Any]:
    """Run requested checks and return a JSON-serializable report."""
    checks = [check_system(), check_dns(host)]
    if include_ping:
        checks.append(check_ping(host))
    checks.extend(check_tcp_port(host, port) for port in ports)
    statuses = [check.status for check in checks]
    overall = "FAIL" if "FAIL" in statuses else "WARN" if "WARN" in statuses else "PASS"
    return {
        "tool": "IT Troubleshooting Toolkit",
        "report_version": 1,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "target": {"host": host, "tcp_ports": ports},
        "overall_status": overall,
        "checks": [asdict(check) for check in checks],
    }


def format_report(report: dict[str, Any]) -> str:
    """Render a concise human-readable report."""
    lines = [
        "IT Troubleshooting Toolkit",
        "=" * 27,
        f"Target: {report['target']['host']}",
        f"Generated (UTC): {report['generated_at_utc']}",
        f"Overall status: {report['overall_status']}",
        "",
    ]
    for check in report["checks"]:
        lines.append(f"[{check['status']}] {check['name']}: {check['summary']}")
        for key, value in check["details"].items():
            lines.append(f"    {key}: {value}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run read-only system and network diagnostics.")
    parser.add_argument("host", help="Hostname or IP address to diagnose")
    parser.add_argument("--port", type=int, action="append", default=[], dest="ports", help="TCP port to test (repeatable), e.g. --port 443")
    parser.add_argument("--no-ping", action="store_true", help="Skip ICMP ping check")
    parser.add_argument("--json", dest="json_path", default="diagnostic-report.json", help="JSON report output path (default: diagnostic-report.json)")
    args = parser.parse_args(argv)

    invalid_ports = [port for port in args.ports if not 1 <= port <= 65535]
    if invalid_ports:
        parser.error(f"Invalid TCP port(s): {invalid_ports}. Valid range is 1-65535.")

    report = build_report(args.host, args.ports, include_ping=not args.no_ping)
    print(format_report(report))
    try:
        output_path = Path(args.json_path)
        output_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"\nJSON report saved to: {output_path.resolve()}")
    except OSError as exc:
        print(f"\nError: could not write JSON report: {exc}", file=sys.stderr)
        return 2
    return 1 if report["overall_status"] == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main())
