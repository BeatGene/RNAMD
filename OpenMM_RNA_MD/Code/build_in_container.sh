#!/usr/bin/env bash
set -euo pipefail
trap 'printf "BUILD FAILED at line %s. Keep build.log and container.\n" "$LINENO" >&2' ERR
[[ "$(uname -s)/$(uname -m)" == Linux/x86_64 ]] || { echo 'Requires Linux x86_64'; exit 1; }
export OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2
export CONDA_REMOTE_CONNECT_TIMEOUT_SECS=20 CONDA_REMOTE_READ_TIMEOUT_SECS=60
export CONDA_REMOTE_MAX_RETRIES=2
# Only this GPU-less builder overrides detection. Target server never does.
export CONDA_OVERRIDE_CUDA=12.6
unset PYTHONPATH PYTHONHOME
BUNDLE=/work/bundle
mkdir -p "$BUNDLE/provenance" /work/bootstrap
ldd --version > "$BUNDLE/provenance/build_glibc.txt"
cat /etc/os-release > "$BUNDLE/provenance/build_os.txt"
date -u > "$BUNDLE/provenance/build_time.txt"
echo '[1/6] Verified Linux Miniforge bootstrap'
if [[ ! -x /opt/conda/bin/conda ]]; then
  python - <<'PY'
from pathlib import Path
import hashlib, urllib.request
path = Path('/work/bootstrap/Miniforge3-Linux-x86_64.sh')
expected = 'bbaf16b3897da24c4be50315934ba74848f617b4495982841d6a0a60e0edbbdf'
url = ('https://github.com/conda-forge/miniforge/releases/download/26.9.4-2/'
       'Miniforge3-26.9.4-2-Linux-x86_64.sh')
if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
    partial = path.with_suffix('.partial')
    with urllib.request.urlopen(url, timeout=60) as source, partial.open('wb') as dest:
        while True:
            chunk = source.read(1024*1024)
            if not chunk: break
            dest.write(chunk)
    if hashlib.sha256(partial.read_bytes()).hexdigest() != expected:
        raise SystemExit('Miniforge checksum mismatch')
    partial.replace(path)
print('Miniforge checksum OK', flush=True)
PY
  bash /work/bootstrap/Miniforge3-Linux-x86_64.sh -b -p /opt/conda
fi
export PATH="/opt/conda/bin:$PATH"
echo '[2/6] Solve independent RNA environment; includes CUDA runtime, not driver'
if [[ ! -f /work/environment_solved.ok ]]; then
  if [[ -e /opt/rna_md ]]; then
    echo 'Partial /opt/rna_md exists; inspect build.log before retrying. No automatic deletion.' >&2
    exit 1
  fi
  conda create -p /opt/rna_md --override-channels -c conda-forge --strict-channel-priority -y \
    python=3.11 'openmm>=8.2,<9' 'ambertools>=24,<27' 'parmed>=4,<5' \
    mdtraj numpy cuda-version=12.6
  touch /work/environment_solved.ok
fi
conda list -p /opt/rna_md --explicit > "$BUNDLE/provenance/conda-explicit.txt"
conda env export -p /opt/rna_md > "$BUNDLE/provenance/environment-resolved.yml"
# A CPU-only package bundle must not pass as CUDA-capable.
/opt/rna_md/bin/python - <<'PY'
from pathlib import Path
import json
p = Path('/opt/rna_md')
records = [json.loads(f.read_text()) for f in (p/'conda-meta').glob('cuda-version-*.json')]
if len(records) != 1 or not records[0]['version'].startswith('12.6'):
    raise SystemExit('Expected CUDA 12.6 Conda runtime constraint')
plugins = list(p.glob('lib/**/libOpenMMCUDA.so'))
if not plugins: raise SystemExit('Missing libOpenMMCUDA.so in solved environment')
print('CUDA plugin packaged:', plugins, flush=True)
PY
echo '[3/6] Copy scripts and pack complete environment'
cp /code/check_environment.py /code/install_offline_server.sh "$BUNDLE/"
cp /code/OFFLINE_STEPS.md "$BUNDLE/"
conda install -p /opt/conda --override-channels -c conda-forge --strict-channel-priority -y conda-pack
if [[ ! -f "$BUNDLE/rna_env_linux_x86_64.tar.gz" ]]; then
  conda-pack -p /opt/rna_md -o "$BUNDLE/rna_env_linux_x86_64.tar.gz"
fi
echo '[4/6] Relocate packed environment and run actual CPU RNA smoke'
if [[ ! -f /work/relocation_ready.ok ]]; then
  if [[ -e /opt/rna_relocated ]]; then
    echo 'Partial relocation exists; inspect log before retrying.' >&2; exit 1
  fi
  mkdir /opt/rna_relocated
  tar -xzf "$BUNDLE/rna_env_linux_x86_64.tar.gz" -C /opt/rna_relocated
  /opt/rna_relocated/bin/python /opt/rna_relocated/bin/conda-unpack
  touch /work/relocation_ready.ok
fi
(
  source /opt/conda/etc/profile.d/conda.sh
  conda activate /opt/rna_relocated
  export CUDA_VISIBLE_DEVICES=''
  python "$BUNDLE/check_environment.py" --platform CPU --output-root "$BUNDLE/provenance/relocation_cpu_checks"
)
echo '[5/6] Record payload hashes'
printf '%s\n' 'linux-64; glibc builder 2.36; Python 3.11; CUDA 12.6; target driver 575.57.08' \
  > "$BUNDLE/provenance/target.txt"
cd "$BUNDLE"
find . -type f ! -name SHA256SUMS -print0 | sort -z | xargs -0 sha256sum > SHA256SUMS
sha256sum -c SHA256SUMS
echo '[6/6] Final transferable archive'
tar -cf /work/openmm_rna_offline_bundle.tar -C "$BUNDLE" .
cd /work
sha256sum openmm_rna_offline_bundle.tar > openmm_rna_offline_bundle.tar.sha256
echo 'RNA_MD_OFFLINE_BUNDLE_CPU_OK'
echo 'GPU execution remains unverified until the server CUDA smoke passes.'
