#!/usr/bin/env python3
"""Read-only DynaRNA installation preflight; Python standard library only.

Writes one JSON report, without installing packages or initializing CUDA.
Does not collect environment variable values, credentials, or process lists.
"""

import argparse
import concurrent.futures
import datetime
import json
import os
import platform
from pathlib import Path
import shutil
import socket
import ssl
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request


PROBES = (
    ("github", "https://github.com/lizxSJTU/DynaRNA"),
    ("github_source_archive", "https://codeload.github.com/lizxSJTU/DynaRNA/tar.gz/refs/heads/main"),
    ("pypi_index", "https://pypi.org/simple/numpy/"),
    ("pypi_files", "https://files.pythonhosted.org/"),
    ("pytorch_cu121_index", "https://download.pytorch.org/whl/cu121/torch/"),
    ("conda_main", "https://repo.anaconda.com/pkgs/main/"),
    ("conda_forge", "https://conda.anaconda.org/conda-forge/"),
    ("zenodo_checkpoint", "https://zenodo.org/records/15600148/files/DynaRNA.pkl"),
)


def command(args, timeout=20):
    try:
        proc = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        return {"returncode": proc.returncode, "stdout": proc.stdout}
    except FileNotFoundError:
        return {"error": "command_not_found"}
    except subprocess.TimeoutExpired:
        return {"error": "timeout"}
    except OSError as exc:
        return {"error": type(exc).__name__}


def conda_report(explicit):
    candidates = [explicit, os.environ.get("CONDA_EXE"), shutil.which("conda")]
    for root in ("miniconda3", "anaconda3", "miniforge3", "mambaforge"):
        candidates.append(str(Path.home() / root / "bin" / "conda"))
    executable = next((str(Path(p).expanduser()) for p in candidates
                       if p and Path(p).expanduser().is_file()), None)
    if executable is None:
        return {"found": False, "hint": "Rerun with --conda /absolute/path/to/bin/conda"}
    result = {"found": True, "executable": executable}
    info = command([executable, "info", "--json"])
    if info.get("returncode") != 0:
        result["info_error"] = info.get("error", "nonzero_exit")
        return result
    try:
        raw = json.loads(info["stdout"])
    except (ValueError, TypeError):
        result["info_error"] = "invalid_json"
        return result
    # Deliberately exclude channels, proxy configuration and raw command output.
    for key in ("conda_version", "python_version", "platform", "root_prefix", "active_prefix"):
        result[key] = raw.get(key)
    result["environment_names"] = sorted({Path(p).name for p in raw.get("envs", [])})
    cached_python = []
    for directory in raw.get("pkgs_dirs", []):
        try:
            for pattern in ("python-3.10*", "python-3.11*"):
                cached_python.extend(p.name for p in Path(directory).glob(pattern))
        except OSError:
            pass
    result["cached_python_package_names"] = sorted(set(cached_python))[:30]
    return result


def network_probe(item, timeout):
    name, url = item
    result = {"name": name, "url": url}
    # HEAD avoids downloading archives/checkpoints. Some servers require GET.
    for method in ("HEAD", "GET"):
        request = urllib.request.Request(
            url, method=method,
            headers={"User-Agent": "DynaRNA-installation-preflight/1.0", "Range": "bytes=0-0"},
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                result.update(
                    status="http_success", http_status=response.status,
                    final_host=urllib.parse.urlsplit(response.url).hostname,
                    content_type=response.headers.get("Content-Type", ""),
                )
                if method == "GET":
                    response.read(1)
            return result
        except urllib.error.HTTPError as exc:
            if exc.code == 405 and method == "HEAD":
                continue
            result.update(status="http_error", http_status=exc.code)
            return result
        except (urllib.error.URLError, OSError) as exc:
            reason = getattr(exc, "reason", exc)
            if isinstance(reason, ssl.SSLError):
                status = "tls_error"
            elif isinstance(reason, socket.gaierror):
                status = "dns_error"
            elif isinstance(reason, (TimeoutError, socket.timeout)):
                status = "timeout"
            else:
                status = "connection_error"
            result.update(status=status, error_type=type(reason).__name__)
            return result
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--conda", help="Absolute path to the conda executable")
    parser.add_argument("--output", type=Path, help="New report path; will not overwrite")
    parser.add_argument("--timeout", type=float, default=6, help="Per-request socket timeout, seconds")
    parser.add_argument("--skip-network", action="store_true")
    args = parser.parse_args()
    if not 0 < args.timeout <= 30:
        parser.error("--timeout must be greater than 0 and at most 30")
    timestamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")
    output = args.output or Path("dynarna_preflight_" + timestamp + ".json")
    if output.exists():
        parser.error("Report already exists; choose a new --output path")
    os_release = {}
    try:
        for line in Path("/etc/os-release").read_text().splitlines():
            key, separator, value = line.partition("=")
            if separator and key in {"NAME", "VERSION", "ID", "VERSION_ID", "PRETTY_NAME"}:
                os_release[key] = value.strip('"')
    except OSError:
        pass
    disk = shutil.disk_usage(Path.cwd())
    report = {
        "schema_version": 1,
        "timestamp_utc": timestamp,
        "system": {"os": platform.system(), "machine": platform.machine(),
                   "kernel": platform.release(), "libc": list(platform.libc_ver()),
                   "os_release": os_release},
        "python": {"version": platform.python_version(), "executable": sys.executable},
        "working_directory_free_gib": round(disk.free / 2**30, 2),
        "conda": conda_report(args.conda),
        "tools_found": {name: bool(shutil.which(name)) for name in ("git", "curl", "tar", "nvidia-smi")},
    }
    gpu = command(["nvidia-smi", "--query-gpu=index,name,driver_version,memory.total,memory.used,utilization.gpu", "--format=csv"], timeout=10)
    report["gpu"] = ({"returncode": 0, "summary_csv": gpu["stdout"].strip()}
                     if gpu.get("returncode") == 0
                     else {"error": gpu.get("error", "nvidia_smi_nonzero_exit")})
    print("System:", json.dumps(report["system"], ensure_ascii=False), flush=True)
    print("Conda:", json.dumps(report["conda"], ensure_ascii=False), flush=True)
    if args.skip_network:
        report["network"] = {"skipped": True}
    else:
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            futures = [pool.submit(network_probe, item, args.timeout) for item in PROBES]
            report["network"] = [future.result() for future in futures]
        for item in report["network"]:
            print("NETWORK", item["name"], item["status"], item.get("http_status", ""), flush=True)
    report["notes"] = [
        "Network success checks only small HTTP requests, not complete package downloads.",
        "An HTTP error proves an HTTP response was received, not that downloads are permitted.",
        "Failure can be caused by DNS, proxy, firewall or TLS; it does not prove a fully offline server.",
        "No packages installed, no CUDA context initialized, no inference run.",
    ]
    with output.open("x", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    print("REPORT:", output.resolve(), flush=True)
    # Exit 0 means the report was produced, not that installation is feasible.
    return 0


if __name__ == "__main__":
    sys.exit(main())
