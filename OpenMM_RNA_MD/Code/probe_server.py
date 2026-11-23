#!/usr/bin/env python3
"""Read-only host/package/network probe; writes reports only. Uses stdlib."""
import argparse
import concurrent.futures
import datetime
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import tempfile


def redact(value):
    return re.sub(r"(https?://)[^\s/@]+(?::[^\s/@]*)?@", r"\1<redacted>@", str(value))


def command(argv, timeout=15):
    try:
        result = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True, timeout=timeout, check=False)
        return {"ok": result.returncode == 0, "returncode": result.returncode,
                "stdout": redact(result.stdout[-40000:]),
                "stderr": redact(result.stderr[-2000:])}
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"ok": False, "error": redact(exc)}


def network_probe(url):
    # A subprocess bounds DNS/TLS time as well as socket-read time.
    code = """import json, urllib.request, sys
try:
    req = urllib.request.Request(sys.argv[1], headers={
        'Range': 'bytes=0-255', 'User-Agent': 'RNA-MD-environment-probe/1'})
    with urllib.request.urlopen(req, timeout=8) as response:
        data = response.read(256)
        print(json.dumps({'status': response.status, 'bytes_read': len(data)}))
except Exception as exc:
    print(json.dumps({'error': type(exc).__name__ + ': ' + str(exc)}))
    sys.exit(1)
"""
    result = command([sys.executable, "-c", code, url], timeout=12)
    try:
        result["response"] = json.loads(result.get("stdout", ""))
        if "error" in result["response"]:
            result["error"] = result["response"]["error"]
    except ValueError:
        pass
    result["url"] = url
    return result


def package_records(prefix):
    names = {"python", "openmm", "ambertools", "parmed", "mdtraj", "numpy",
             "cuda-version", "cuda-cudart", "cuda-nvrtc", "cudatoolkit"}
    records = []
    for path in sorted((Path(prefix) / "conda-meta").glob("*.json")):
        try:
            record = json.loads(path.read_text())
            if record.get("name") in names:
                records.append({k: record.get(k) for k in ("name", "version", "build", "subdir")})
        except (OSError, ValueError):
            continue
    return {"prefix": str(prefix), "packages": records}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--conda-exe", default="")
    parser.add_argument("--output-root", type=Path,
                        default=Path.home() / "openmm_rna_setup" / "probes")
    parser.add_argument("--skip-network", action="store_true")
    args = parser.parse_args()
    args.output_root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = Path(tempfile.mkdtemp(prefix="probe_" + stamp + "_", dir=args.output_root))
    print("Probe report directory:", out, flush=True)
    report = {"schema_version": 1, "utc": stamp,
              "host": {"os": platform.system(), "machine": platform.machine(),
                       "libc": platform.libc_ver(), "python": sys.version,
                       "python_executable": sys.executable, "cpu_count": os.cpu_count(),
                       "disk_free_GiB_at_output": round(shutil.disk_usage(out).free / 2**30, 2),
                       "cuda_visible_devices": os.environ.get("CUDA_VISIBLE_DEVICES"),
                       "slurm_job_id": os.environ.get("SLURM_JOB_ID")},
              "commands": {}, "environments": [], "network": [],
              "network_skipped": args.skip_network}
    jobs = {
        "nvidia_smi": ["nvidia-smi", "--query-gpu=index,uuid,name,driver_version,memory.total,memory.free",
                       "--format=csv,noheader,nounits"],
        "nvcc": ["nvcc", "--version"],
    }
    if args.conda_exe:
        jobs["conda_info"] = [args.conda_exe, "info", "--json"]
        jobs["conda_envs"] = [args.conda_exe, "env", "list", "--json"]
    urls = ["https://conda.anaconda.org/conda-forge/linux-64/repodata.json.zst",
            "https://conda.anaconda.org/conda-forge/noarch/repodata.json.zst",
            "https://pypi.org/simple/openmm/"]
    # No dump of environment variables, .condarc, tokens, or unrelated files.
    with concurrent.futures.ThreadPoolExecutor(max_workers=7) as pool:
        futures = {pool.submit(command, argv, 25): name for name, argv in jobs.items()}
        net = [] if args.skip_network else [pool.submit(network_probe, url) for url in urls]
        for future in concurrent.futures.as_completed(futures):
            name = futures[future]
            value = future.result()
            if name in {"conda_info", "conda_envs"} and value.get("ok"):
                try:
                    raw = json.loads(value["stdout"])
                    if name == "conda_info":
                        value = {"ok": True, "info": {key: raw.get(key) for key in
                                 ("conda_version", "platform", "root_prefix", "active_prefix",
                                  "envs_dirs", "pkgs_dirs", "virtual_pkgs")}}
                    else:
                        value = {"ok": True, "envs": raw.get("envs", [])}
                except ValueError:
                    value = {"ok": False, "error": "Conda returned invalid or oversized JSON"}
            report["commands"][name] = value
            print(name + ": " + ("OK" if value.get("ok") else "unavailable/failed"), flush=True)
        report["network"] = [f.result() for f in net]
    prefixes = report["commands"].get("conda_envs", {}).get("envs", [])
    report["environments"] = [package_records(p) for p in prefixes]
    report["cached_md_archives"] = []
    cache_dirs = report["commands"].get("conda_info", {}).get("info", {}).get("pkgs_dirs", []) or []
    for directory in cache_dirs:
        try:
            matches = sorted(p.name for p in Path(directory).iterdir()
                             if p.name.startswith(("openmm-", "ambertools-", "parmed-", "mdtraj-"))
                             and p.name.endswith((".conda", ".tar.bz2")))
            report["cached_md_archives"].append({"directory": directory, "archives": matches[:60]})
        except OSError as exc:
            report["cached_md_archives"].append({"directory": directory, "error": str(exc)})
    forge = report["network"][:2]
    reachable = len(forge) == 2 and all(x.get("ok") for x in forge)
    report["next_step"] = (
        "Conda-forge metadata reachable; online solve/download still needs verification."
        if reachable else "Network not established; inspect errors/cache before preparing an offline bundle.")
    if args.skip_network:
        report["next_step"] = "Network probes explicitly skipped; connectivity is unknown."
    summary = ["RNA_MD_SERVER_PROBE_DONE", "OS/arch: " + platform.system() + "/" + platform.machine(),
               "libc: " + " ".join(platform.libc_ver()),
               "Disk free at report directory (GiB): " + str(report["host"]["disk_free_GiB_at_output"]),
               "CUDA_VISIBLE_DEVICES: " + str(report["host"]["cuda_visible_devices"]),
               "GPU records (index, UUID, name, driver, total/free MiB):",
               report["commands"]["nvidia_smi"].get("stdout", "not available").strip(),
               "Conda: " + json.dumps(report["commands"].get("conda_info", {}), ensure_ascii=False),
               "Existing environments with relevant MD packages:"]
    for item in report["environments"]:
        if any(p["name"] in {"openmm", "ambertools"} for p in item["packages"]):
            summary.append(json.dumps(item, ensure_ascii=False))
    summary.append("Network probes (HTTP only; not an install test):")
    for item in report["network"]:
        summary.append(("OK " if item.get("ok") else "FAIL ") + item["url"])
        if not item.get("ok"):
            summary.append(item.get("error", item.get("stderr", "")))
    summary.extend([report["next_step"], "Report: " + str(out / "report.json")])
    (out / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    (out / "summary.txt").write_text("\n".join(summary) + "\n")
    print("\n".join(summary), flush=True)


if __name__ == "__main__":
    main()
