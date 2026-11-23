#!/usr/bin/env python3
"""Read-only host/network inventory; Python 3.6+, standard library only.

Does not install packages, load torch, download weights, or launch GPU work.
Network checks request HTTP headers only; their success does not prove large
package/checkpoint downloads work. Use --skip-network for local inspection.
"""

import argparse
from concurrent.futures import ThreadPoolExecutor
import datetime
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import sysconfig


URLS = [
    ("GitHub source", "https://github.com/microsoft/bioemu2"),
    ("GitHub archive", "https://codeload.github.com/microsoft/bioemu2/tar.gz/refs/heads/main"),
    ("PyPI index", "https://pypi.org/simple/biopython/"),
    ("PyPI files host", "https://files.pythonhosted.org/"),
    ("PyTorch CUDA 12.6 index", "https://download.pytorch.org/whl/cu126/torch/"),
    ("Hugging Face model config", "https://huggingface.co/microsoft/bioemu2/resolve/main/checkpoints/bioemu2-preview/config.yaml"),
    ("Hugging Face checkpoint redirects", "https://huggingface.co/microsoft/bioemu2/resolve/main/checkpoints/bioemu2-preview/checkpoint.ckpt"),
    ("Conda defaults metadata", "https://repo.anaconda.com/pkgs/main/noarch/current_repodata.json"),
    ("conda-forge metadata", "https://conda.anaconda.org/conda-forge/noarch/current_repodata.json"),
]


def run(args, timeout=15):
    try:
        completed = subprocess.run(
            args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            universal_newlines=True, timeout=timeout,
        )
        return completed.returncode, completed.stdout.strip()
    except (OSError, subprocess.TimeoutExpired) as exc:
        return -1, "{}: {}".format(type(exc).__name__, exc)


def show_command(label, args):
    print("\n[{}]".format(label))
    code, output = run(args)
    print("return_code={}".format(code))
    print(output or "(empty)")


def probe(item):
    label, url = item
    if not shutil.which("curl"):
        return label, "SKIPPED: curl not found"
    code, output = run([
        "curl", "--head", "--location", "--silent", "--show-error",
        "--connect-timeout", "5", "--max-time", "12", "--retry", "0",
        "--output", os.devnull, "--write-out",
        "http=%{http_code} redirects=%{num_redirects} tls_verify=%{ssl_verify_result}",
        url,
    ], timeout=15)
    return label, "curl_exit={} {}".format(code, output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-network", action="store_true")
    args = parser.parse_args()
    print("BioEmu2 server preflight (diagnostic report, not an installation pass)")
    print("utc={}".format(datetime.datetime.utcnow().isoformat() + "Z"))
    print("system={} machine={} libc={}".format(
        platform.system(), platform.machine(), platform.libc_ver()))
    print("python={} executable={}".format(sys.version.replace("\n", " "), sys.executable))
    include_path = sysconfig.get_path("include")
    print("current_python_headers={}".format(
        bool(include_path and (Path(include_path) / "Python.h").is_file())))
    print("NOTE: current Python is for probing; BioEmu2 will use a new Python 3.12 environment.")
    os_release = Path("/etc/os-release")
    if os_release.is_file():
        for line in os_release.read_text().splitlines():
            if line.startswith(("PRETTY_NAME=", "ID=", "VERSION_ID=")):
                print(line)
    disk = shutil.disk_usage(str(Path.home()))
    print("home_disk_free_GiB={:.1f}".format(disk.free / (1024 ** 3)))
    show_command("glibc", ["ldd", "--version"])
    show_command("C compiler", ["gcc", "--version"])
    show_command("CUDA toolkit (optional inventory)", ["nvcc", "--version"])
    show_command("GPU inventory; no allocation", [
        "nvidia-smi", "--query-gpu=index,name,driver_version,memory.total,memory.free,utilization.gpu",
        "--format=csv",
    ])
    show_command("GPU compute capability", [
        "nvidia-smi", "--query-gpu=name,compute_cap", "--format=csv",
    ])
    print("\n[Conda]")
    candidates = [os.environ.get("CONDA_EXE"), shutil.which("conda"),
                  str(Path.home() / "miniconda3/bin/conda")]
    conda = next((p for p in candidates if p and Path(p).is_file()), None)
    if conda:
        code, output = run([conda, "info", "--json"], timeout=25)
        print("return_code={}".format(code))
        try:
            info = json.loads(output)
            # Do not dump channel/proxy configuration, which may contain credentials.
            for key in ("conda_version", "platform", "root_prefix", "active_prefix", "envs"):
                print("{}={}".format(key, info.get(key)))
        except (ValueError, TypeError):
            print("Conda JSON unavailable; run conda --version and conda env list manually.")
    else:
        print("Conda executable not found automatically; run conda --version and conda env list manually.")
    print("\n[Network HEAD probes; no package/model bodies downloaded]")
    if args.skip_network:
        print("SKIPPED by --skip-network")
    else:
        with ThreadPoolExecutor(max_workers=5) as pool:
            for label, result in pool.map(probe, URLS):
                print("{}: {}".format(label, result))
    print("\nInterpretation: HTTP 2xx/3xx suggests endpoint reachability only.")
    print("HTTP 403/404/405 does not prove the machine is offline; inspect per-site results.")
    print("curl errors 5/6: proxy/DNS; 7: connection; 28: timeout; 60: certificate verification.")
    print("A redirected checkpoint HEAD is still not a complete large-file download test.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
