#!/usr/bin/env bash
set -euo pipefail
BUNDLE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_PREFIX="${1:-$HOME/miniconda3/envs/dynarna}"
SOURCE_DIR="${2:-$HOME/Code/DynaRNA}"
[[ "$(uname -s)" == Linux && "$(uname -m)" == x86_64 ]] || { echo 'Expected Linux x86_64'; exit 1; }
[[ "$ENV_PREFIX" == /* && "$SOURCE_DIR" == /* ]] || { echo 'Use absolute paths'; exit 1; }
[[ ! -e "$ENV_PREFIX" && ! -e "$SOURCE_DIR" ]] || { echo 'Destination exists; choose two new paths. No files overwritten.'; exit 1; }
echo '[1/4] Verify bundle files'
(cd "$BUNDLE" && sha256sum -c SHA256SUMS)
echo '[2/4] Extract new standalone conda environment'
mkdir -p "$ENV_PREFIX"
tar -xzf "$BUNDLE/dynarna_env_linux_x86_64.tar.gz" -C "$ENV_PREFIX"
# Use the extracted interpreter explicitly, never the active Protenix interpreter.
"$ENV_PREFIX/bin/python" "$ENV_PREFIX/bin/conda-unpack"
echo '[3/4] Install source, checkpoint and helper scripts without pip/network'
mkdir -p "$SOURCE_DIR"
cp -R "$BUNDLE/source/." "$SOURCE_DIR/"
mkdir -p "$SOURCE_DIR/ckpt" "$SOURCE_DIR/install_helpers" "$SOURCE_DIR/install_provenance"
cp "$BUNDLE/model/DynaRNA.pkl" "$SOURCE_DIR/ckpt/"
cp "$BUNDLE/check_installation.py" "$BUNDLE/run_official_inference.py" "$SOURCE_DIR/install_helpers/"
cp -R "$BUNDLE/provenance/." "$SOURCE_DIR/install_provenance/"
echo '[4/4] CPU model verification (GPU is not used)'
OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 CUDA_VISIBLE_DEVICES='' \
  "$ENV_PREFIX/bin/python" "$SOURCE_DIR/install_helpers/check_installation.py" \
  --source "$SOURCE_DIR" --checkpoint "$SOURCE_DIR/ckpt/DynaRNA.pkl" --device cpu
printf '\nOffline installation and CPU check passed. GPU check is still required.\nEnvironment: %s\nSource: %s\n' "$ENV_PREFIX" "$SOURCE_DIR"
