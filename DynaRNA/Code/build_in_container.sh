#!/usr/bin/env bash
set -euo pipefail
trap 'printf "\nBuild failed at line %s. Preserve container and build.log.\n" "$LINENO" >&2' ERR
[[ "$(uname -m)" == x86_64 ]] || { echo 'Expected Linux x86_64'; exit 1; }
export PIP_DISABLE_PIP_VERSION_CHECK=1
export PIP_CACHE_DIR=/work/pip-cache
export OMP_NUM_THREADS=2
export OPENBLAS_NUM_THREADS=2
export MPLBACKEND=Agg
BUNDLE=/work/bundle
mkdir -p "$BUNDLE/provenance"
date -u > "$BUNDLE/provenance/build_started_utc.txt"
uname -a > "$BUNDLE/provenance/build_host.txt"
ldd --version >> "$BUNDLE/provenance/build_host.txt"

echo '[1/7] Official source, checkpoint and Linux Miniforge'
/usr/local/bin/python /code/download_assets.py /work
if [[ ! -x /opt/conda/bin/conda ]]; then
  bash /work/bootstrap/Miniforge3-Linux-x86_64.sh -b -p /opt/conda
fi
export PATH="/opt/conda/bin:$PATH"
echo '[2/7] Independent Python 3.10 environment'
if [[ ! -x /opt/dynarna/bin/python ]]; then
  conda create --prefix /opt/dynarna --override-channels -c conda-forge \
    python=3.10 pip setuptools wheel libgcc-ng libstdcxx-ng libgomp -y
fi
# Keep packaging tools separate from both Miniforge base (currently Python 3.14)
# and the target environment. conda-pack 0.8.1 imports removed pkg_resources;
# 0.9.2 uses importlib.resources. Run it under the container's Python 3.10.
PACK_TOOLS=/opt/dynarna-pack-tools
if [[ ! -x "$PACK_TOOLS/bin/python" ]]; then
  /usr/local/bin/python -m venv "$PACK_TOOLS"
fi
"$PACK_TOOLS/bin/python" -m pip install 'conda-pack==0.9.2'
"$PACK_TOOLS/bin/python" -m pip check
"$PACK_TOOLS/bin/python" - <<'PY'
import sys
import conda_pack
from importlib.metadata import version
assert sys.version_info[:2] == (3, 10), sys.version
assert version('conda-pack') == '0.9.2'
print('Packaging tool imports OK:', sys.version.split()[0], version('conda-pack'), flush=True)
PY
"$PACK_TOOLS/bin/conda-pack" --help > "$BUNDLE/provenance/conda_pack_help.txt"
"$PACK_TOOLS/bin/python" -m pip freeze > "$BUNDLE/provenance/pack_tools_freeze.txt"
echo '[3/7] CUDA PyTorch and inference dependencies'
/opt/dynarna/bin/python -m pip install 'torch==2.2.2' --index-url https://download.pytorch.org/whl/cu121
/opt/dynarna/bin/python -m pip install -r /code/requirements-inference.txt
/opt/dynarna/bin/python -m pip check
echo '[4/7] Source extraction and CPU model check'
if [[ ! -d "$BUNDLE/source" ]]; then
  mkdir "$BUNDLE/source"
  tar -xzf "$BUNDLE/dynarna_source.tar.gz" -C "$BUNDLE/source" --strip-components=1
fi
cp /code/check_installation.py /code/run_official_inference.py \
   /code/install_offline_server.sh /code/requirements-inference.txt "$BUNDLE/"
CUDA_VISIBLE_DEVICES='' /opt/dynarna/bin/python "$BUNDLE/check_installation.py" \
  --source "$BUNDLE/source" --checkpoint "$BUNDLE/model/DynaRNA.pkl" --device cpu \
  | tee "$BUNDLE/provenance/container_cpu_check.txt"
echo '[5/7] Versions and relocatable environment'
/opt/dynarna/bin/python -m pip freeze > "$BUNDLE/provenance/pip_freeze.txt"
conda list --prefix /opt/dynarna --explicit > "$BUNDLE/provenance/conda_explicit.txt"
# No --ignore-missing-files: an inconsistent conda environment must fail packaging.
"$PACK_TOOLS/bin/conda-pack" --prefix /opt/dynarna --format tar.gz --compress-level 1 \
  --n-threads 2 --force --output "$BUNDLE/dynarna_env_linux_x86_64.tar.gz"
echo '[6/7] Per-file checksums'
printf 'CPU import, strict checkpoint loading and one reverse step passed. GPU and full inference remain untested.\n' \
  > "$BUNDLE/BUILD_STATUS.txt"
(cd "$BUNDLE" && find . -type f ! -name SHA256SUMS -print0 \
  | LC_ALL=C sort -z | xargs -0 sha256sum > SHA256SUMS)
echo '[7/7] Transfer archive'
(cd /work && tar -cf dynarna_offline_bundle.tar bundle)
(cd /work && sha256sum dynarna_offline_bundle.tar > dynarna_offline_bundle.tar.sha256)
echo 'BUILD COMPLETE'
ls -lh /work/dynarna_offline_bundle.tar /work/dynarna_offline_bundle.tar.sha256

