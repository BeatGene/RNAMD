#!/usr/bin/env bash
set -euo pipefail
trap 'printf "\nBUILD FAILED at line %s. Keep container and build.log for diagnosis.\n" "$LINENO" >&2' ERR
[[ "$(uname -m)" == x86_64 ]] || { echo 'Expected Linux x86_64'; exit 1; }
export DEBIAN_FRONTEND=noninteractive
export PIP_DISABLE_PIP_VERSION_CHECK=1
export PIP_CACHE_DIR=/work/pip-cache
export HF_HOME=/work/hf-cache
export HF_HUB_DISABLE_XET=1
export OMP_NUM_THREADS=2
export OPENBLAS_NUM_THREADS=2
BUNDLE=/work/bundle
mkdir -p "$BUNDLE/provenance" "$BUNDLE/model" /work/bootstrap
date -u > "$BUNDLE/provenance/build_started_utc.txt"
uname -a > "$BUNDLE/provenance/build_host.txt"
ldd --version >> "$BUNDLE/provenance/build_host.txt"
cat /etc/os-release >> "$BUNDLE/provenance/build_host.txt"

echo '[1/8] Container tools and Linux Miniforge'
# The slim image can use HTTP APT sources even when HTTPS probes succeed.
# Change only official Debian URLs inside this container. Keep signed metadata
# and normal TLS verification; support both deb822 .sources and legacy .list.
python - <<'PY'
from pathlib import Path
import re
import shutil
import urllib.request

files = [Path('/etc/apt/sources.list')]
directory = Path('/etc/apt/sources.list.d')
files.extend(sorted(directory.glob('*.sources')))
files.extend(sorted(directory.glob('*.list')))
pattern = r'\bhttp://(deb\.debian\.org|security\.debian\.org|ftp\.debian\.org)(?=/|\s|$)'
for path in files:
    if not path.is_file():
        continue
    old = path.read_text()
    new = re.sub(pattern, r'https://\1', old)
    if new != old:
        backup = path.with_name(path.name + '.bioemu2-http.bak')
        if not backup.exists():
            shutil.copyfile(path, backup)
        path.write_text(new)
        print('APT source changed to HTTPS:', path, flush=True)

for url in (
    'https://deb.debian.org/debian/dists/bookworm/InRelease',
    'https://deb.debian.org/debian-security/dists/bookworm-security/InRelease',
):
    try:
        with urllib.request.urlopen(url, timeout=20) as response:
            response.read(64)
            print('Debian HTTPS OK:', response.status, url, flush=True)
    except Exception as exc:
        raise SystemExit(f'Debian HTTPS probe failed: {url}: {exc}. '
                         'Keep the container; diagnose its HTTPS access before retrying.')
PY
APT_NETWORK=(-o Acquire::Retries=3 -o Acquire::http::Timeout=20 -o Acquire::https::Timeout=20)
apt-get "${APT_NETWORK[@]}" -o APT::Update::Error-Mode=any update
apt-get "${APT_NETWORK[@]}" install -y --no-install-recommends ca-certificates curl git bzip2 gcc g++
MINIFORGE_VERSION=26.9.4-2
INSTALLER=Miniforge3-Linux-x86_64.sh
# SHA256 published for the versioned Linux x86_64 release asset:
# https://github.com/conda-forge/miniforge/releases/expanded_assets/26.9.4-2
MINIFORGE_SHA256=bbaf16b3897da24c4be50315934ba74848f617b4495982841d6a0a60e0edbbdf
if [[ ! -x /opt/conda/bin/conda ]]; then
  if [[ -f "/work/bootstrap/$INSTALLER" ]] && \
      printf '%s  %s\n' "$MINIFORGE_SHA256" "/work/bootstrap/$INSTALLER" | sha256sum --check --status; then
    echo "Reusing verified Miniforge $MINIFORGE_VERSION installer"
  else
    BASE_URL="https://github.com/conda-forge/miniforge/releases/download/$MINIFORGE_VERSION"
    VERSIONED_INSTALLER="Miniforge3-$MINIFORGE_VERSION-Linux-x86_64.sh"
    curl -fL --retry 3 --connect-timeout 20 "$BASE_URL/$VERSIONED_INSTALLER" \
      -o "/work/bootstrap/$INSTALLER.partial"
    printf '%s  %s\n' "$MINIFORGE_SHA256" "/work/bootstrap/$INSTALLER.partial" | sha256sum -c -
    mv "/work/bootstrap/$INSTALLER.partial" "/work/bootstrap/$INSTALLER"
  fi
  # This manifest records the pinned published hash; it is generated locally,
  # not fetched from a nonexistent unversioned .sha256 release asset.
  printf '%s  %s\n' "$MINIFORGE_SHA256" "$INSTALLER" > "/work/bootstrap/$INSTALLER.sha256"
  (cd /work/bootstrap && sha256sum -c "$INSTALLER.sha256")
  bash "/work/bootstrap/$INSTALLER" -b -p /opt/conda
fi
printf '%s\n' "$MINIFORGE_VERSION" > "$BUNDLE/provenance/miniforge_version.txt"
sha256sum /work/bootstrap/Miniforge3-Linux-x86_64.sh > "$BUNDLE/provenance/miniforge_sha256.txt"
export PATH="/opt/conda/bin:$PATH"

echo '[2/8] New Python 3.12 Conda environment'
if [[ ! -x /opt/bioemu2/bin/python ]]; then
  conda create --prefix /opt/bioemu2 --override-channels -c conda-forge \
    python=3.12 pip 'setuptools>=77.0.3' wheel libgcc-ng libstdcxx-ng libgomp -y
fi
/opt/conda/bin/python -m pip install conda-pack
# Keep Conda-owned build tools under Conda management. Repair environments made
# by the earlier script, which upgraded Conda pip 26.2.2 to PyPI pip 26.3.
# Reinstall the original exact tool version/build using cached Conda packages.
# Use normal MatchSpecs: Conda 26.9 explicit URL installs skip relinking packages
# whose records match, even if --force-reinstall is passed and files are absent.
/opt/conda/bin/python - <<'PY'
import importlib.metadata as metadata
import json
from pathlib import Path
import subprocess

prefix = Path('/opt/bioemu2')
site = prefix / 'lib/python3.12/site-packages'
installed = {}
for dist in metadata.distributions(path=[str(site)]):
    name = dist.metadata.get('Name', '').lower().replace('_', '-')
    installed.setdefault(name, []).append(dist.version)
records = {}
for path in (prefix / 'conda-meta').glob('*.json'):
    record = json.loads(path.read_text())
    if record.get('name') in ('pip', 'setuptools', 'wheel'):
        records[record['name']] = record
repairs = []
for name in ('pip', 'setuptools', 'wheel'):
    if name not in records:
        raise SystemExit(f'Conda record missing for {name}; inspect environment before packaging.')
    record = records[name]
    version = record['version']
    tracked_metadata = [
        file for file in record.get('files', [])
        if '.dist-info/' in file and file.endswith(('/METADATA', '/RECORD', '/INSTALLER'))
    ]
    if (installed.get(name) != [version] or
            not all((prefix / file).is_file() for file in tracked_metadata)):
        url = record.get('url')
        if not url or not url.startswith('https://conda.anaconda.org/conda-forge/'):
            raise SystemExit(f'Unexpected original Conda archive URL for {name}: {url}')
        repairs.append((name, version, record['build'], url))
if repairs:
    print('Restoring original Conda tools:', [(n, v) for n, v, _, _ in repairs], flush=True)
    manifest = Path('/work/bundle/provenance/conda_tools_repair.txt')
    specs = [f'{name}={version}={build}' for name, version, build, _ in repairs]
    manifest.write_text('Exact Conda MatchSpecs (not an @EXPLICIT install file):\n' +
                        '\n'.join(specs) + '\n\nOriginal package URLs:\n' +
                        ''.join(url + '\n' for _, _, _, url in repairs))
    # Remove the PyPI distribution first to avoid leaving a second .dist-info.
    # This uninstalls only affected build tools, never BioEmu2 or torch.
    names = [name for name, _, _, _ in repairs if installed.get(name)]
    if names:
        subprocess.run([str(prefix / 'bin/python'), '-m', 'pip', 'uninstall', '-y', *names], check=True)
    subprocess.run([
        '/opt/conda/bin/conda', 'install', '--prefix', str(prefix), '--offline',
        '--force-reinstall', '--freeze-installed', '--override-channels',
        '-c', 'conda-forge', '-y', *specs,
    ], check=True)
    for name, version, _, _ in repairs:
        actual = [
            dist.version for dist in metadata.distributions(path=[str(site)])
            if dist.metadata.get('Name', '').lower().replace('_', '-') == name
        ]
        if actual != [version]:
            raise SystemExit(f'Conda restoration failed for {name}: expected {[version]}, got {actual}')
        for file in records[name].get('files', []):
            if ('.dist-info/' in file and file.endswith(('/METADATA', '/RECORD', '/INSTALLER'))
                    and not (prefix / file).is_file()):
                raise SystemExit(f'Conda restoration did not restore {file}')
    print('Conda tool restoration verified.', flush=True)
else:
    print('Conda-owned pip/setuptools/wheel metadata OK; no upgrade performed.', flush=True)
# A zero-exit Conda transaction is insufficient: prove pip actually imports
# and runs before any subsequent install or environment packaging.
subprocess.run([str(prefix / 'bin/python'), '-m', 'pip', '--version'], check=True)
PY

echo '[3/8] Source snapshot (retained on resume; no automatic git pull)'
if [[ ! -d /work/source/.git ]]; then
  git clone --depth 1 https://github.com/microsoft/bioemu2.git /work/source
fi
git -C /work/source rev-parse HEAD > "$BUNDLE/provenance/source_commit.txt"
# Refuse unresolved LFS pointers, rather than silently package missing assets.
if git -C /work/source grep -l '^version https://git-lfs.github.com/spec/v1$'; then
  echo 'Source contains Git LFS pointers. Fetch LFS assets before building.' >&2
  exit 1
fi
git -C /work/source archive --format=tar.gz --prefix=bioemu2-source/ HEAD \
  > "$BUNDLE/bioemu2_source.tar.gz"

echo '[4/8] Official CUDA 12 extra; full dependencies'
/opt/bioemu2/bin/python -m pip install '/work/source[cuda12]' \
  --extra-index-url https://download.pytorch.org/whl/cu126
/opt/bioemu2/bin/python -m pip check
/opt/bioemu2/bin/python -m pip freeze > "$BUNDLE/provenance/pip_freeze.txt"
/opt/bioemu2/bin/python -m pip list --format=json > "$BUNDLE/provenance/pip_list.json"
conda list --prefix /opt/bioemu2 --explicit > "$BUNDLE/provenance/conda_explicit.txt"
cp /code/check_installation.py /code/install_offline_server.sh "$BUNDLE/"

echo '[5/8] CPU import and standard RNA preparation with network denied'
CUDA_VISIBLE_DEVICES='' HF_HUB_OFFLINE=1 \
  /opt/bioemu2/bin/python "$BUNDLE/check_installation.py" \
  | tee "$BUNDLE/provenance/container_cpu_check.txt"
CUDA_VISIBLE_DEVICES='' /opt/bioemu2/bin/bioemu2 propagate --help \
  > "$BUNDLE/provenance/propagate_help.txt"

echo '[6/8] Matching local checkpoint/config at a recorded Hugging Face revision'
/opt/bioemu2/bin/python - <<'PY'
from pathlib import Path
import shutil
from huggingface_hub import HfApi, hf_hub_download

root = Path('/work/bundle')
revision_file = root / 'provenance/model_revision.txt'
if revision_file.exists():
    revision = revision_file.read_text().strip()
else:
    revision = HfApi().model_info('microsoft/bioemu2').sha
    revision_file.write_text(revision + '\n')
print('Hugging Face revision:', revision, flush=True)
for name in ('checkpoint.ckpt', 'config.yaml'):
    path = hf_hub_download(
        repo_id='microsoft/bioemu2', revision=revision,
        filename=f'checkpoints/bioemu2-preview/{name}',
        local_dir='/work/downloads',
    )
    # Copy real files, not Hugging Face cache symlinks.
    shutil.copyfile(path, root / 'model' / name)
    print(name, (root / 'model' / name).stat().st_size, 'bytes', flush=True)
PY

echo '[7/8] Relocatable Conda environment (no editable install)'
# Do not ignore missing files or editable packages. A failed pack is not a valid bundle.
/opt/conda/bin/conda-pack --prefix /opt/bioemu2 --format tar.gz \
  --compress-level 1 --n-threads 2 --force \
  --output "$BUNDLE/bioemu2_env_linux_x86_64.tar.gz"

echo '[8/8] SHA256 manifest and transfer archive'
printf 'CPU checks completed; GPU kernels/model loading/propagation require server validation.\n' \
  > "$BUNDLE/BUILD_STATUS.txt"
(cd "$BUNDLE" && find . -type f ! -name SHA256SUMS -print0 \
  | LC_ALL=C sort -z | xargs -0 sha256sum > SHA256SUMS)
(cd /work && tar -cf bioemu2_offline_bundle.tar bundle)
(cd /work && sha256sum bioemu2_offline_bundle.tar > bioemu2_offline_bundle.tar.sha256)
echo 'BUILD COMPLETE'
ls -lh /work/bioemu2_offline_bundle.tar /work/bioemu2_offline_bundle.tar.sha256
