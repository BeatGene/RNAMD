#!/usr/bin/env python3
"""Download official Linux bootstrap, versioned source, and checked model asset."""
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys
import time
import urllib.request


def fetch(url, destination, expected=None):
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    def valid():
        if not destination.is_file():
            return False
        if expected is None:
            return destination.stat().st_size > 0
        algorithm, digest = expected.split(":", 1)
        h = hashlib.new(algorithm)
        with destination.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                h.update(chunk)
        return h.hexdigest() == digest
    if valid():
        print("Reuse:", destination, flush=True)
        return
    partial = destination.with_name(destination.name + ".partial")
    for attempt in range(3):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "DynaRNA-offline-builder/1.0"})
            with urllib.request.urlopen(request, timeout=60) as response, partial.open("wb") as handle:
                shutil.copyfileobj(response, handle, length=1024 * 1024)
            if expected:
                algorithm, digest = expected.split(":", 1)
                h = hashlib.new(algorithm)
                with partial.open("rb") as handle:
                    for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                        h.update(chunk)
                if h.hexdigest() != digest:
                    raise ValueError("Published checksum mismatch for " + destination.name)
            partial.replace(destination)
            print("Downloaded:", destination, destination.stat().st_size, "bytes", flush=True)
            return
        except Exception:
            if attempt == 2:
                raise
            time.sleep(2)


def main():
    work = Path(sys.argv[1]).resolve()
    bootstrap = work / "bootstrap"
    bundle = work / "bundle"
    provenance = bundle / "provenance"
    provenance.mkdir(parents=True, exist_ok=True)
    # Pinned published SHA256, also used by the existing BioEmu2 offline builder.
    version = "26.9.4-2"
    fetch(
        "https://github.com/conda-forge/miniforge/releases/download/" + version +
        "/Miniforge3-" + version + "-Linux-x86_64.sh",
        bootstrap / "Miniforge3-Linux-x86_64.sh",
        "sha256:bbaf16b3897da24c4be50315934ba74848f617b4495982841d6a0a60e0edbbdf",
    )
    commit_file = provenance / "source_commit.txt"
    if not commit_file.exists():
        fetch("https://api.github.com/repos/lizxSJTU/DynaRNA/commits/main", bootstrap / "source_commit.json")
        commit = json.loads((bootstrap / "source_commit.json").read_text())["sha"]
        if not re.fullmatch(r"[0-9a-f]{40}", commit):
            raise ValueError("Invalid GitHub commit")
        commit_file.write_text(commit + "\n")
    commit = commit_file.read_text().strip()
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("Invalid recorded GitHub commit")
    fetch("https://codeload.github.com/lizxSJTU/DynaRNA/tar.gz/" + commit,
          bundle / "dynarna_source.tar.gz")
    metadata_path = bootstrap / "zenodo_record.json"
    fetch("https://zenodo.org/api/records/15600148", metadata_path)
    metadata = json.loads(metadata_path.read_text())
    asset = next(item for item in metadata["files"] if item["key"] == "DynaRNA.pkl")
    checksum = asset["checksum"]
    algorithm, digest = checksum.split(":", 1)
    if algorithm not in {"md5", "sha256"} or not re.fullmatch(r"[0-9a-f]+", digest):
        raise ValueError("Unexpected Zenodo checksum")
    fetch("https://zenodo.org/records/15600148/files/DynaRNA.pkl",
          bundle / "model" / "DynaRNA.pkl", checksum)
    (provenance / "zenodo_asset.json").write_text(json.dumps({
        "record": 15600148, "filename": "DynaRNA.pkl", "published_checksum": checksum,
        "reported_size": asset.get("size"),
    }, indent=2) + "\n")


if __name__ == "__main__":
    main()

