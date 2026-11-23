#!/usr/bin/env bash
set -euo pipefail
trap 'printf "\nINSTALL FAILED at line %s. Keep the log and partial target for diagnosis.\n" "$LINENO" >&2' ERR
BUNDLE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_DIR="${1:-$HOME/miniconda3/envs/bioemu2}"
[[ "$(uname -s)" == Linux && "$(uname -m)" == x86_64 ]] || {
  echo 'Expected Linux x86_64'; exit 1;
}
[[ "$ENV_DIR" == /* && "$ENV_DIR" != *' '* ]] || {
  echo 'Environment path must be absolute and must not contain spaces'; exit 1;
}
if [[ -e "$ENV_DIR" || -L "$ENV_DIR" ]]; then
  printf 'Refusing to overwrite existing target: %s\n' "$ENV_DIR" >&2
  exit 1
fi
echo '[1/5] Verify every bundled file before installing'
(cd "$BUNDLE_DIR" && sha256sum -c SHA256SUMS)
echo '[2/5] Extract new Conda environment'
mkdir -p "$ENV_DIR"
tar -xzf "$BUNDLE_DIR/bioemu2_env_linux_x86_64.tar.gz" -C "$ENV_DIR"
echo '[3/5] Fix relocated prefixes using the new Python'
# A packed conda-unpack shebang still points to the build machine until fixed.
env -u PYTHONPATH -u PYTHONHOME "$ENV_DIR/bin/python" "$ENV_DIR/bin/conda-unpack"
echo '[4/5] CPU-only offline checks'
# Use a child shell so activating the new environment cannot change caller's environment.
(
  unset PYTHONPATH PYTHONHOME
  source "$HOME/miniconda3/etc/profile.d/conda.sh"
  conda activate "$ENV_DIR"
  export CUDA_VISIBLE_DEVICES=''
  export HF_HUB_OFFLINE=1
  export PIP_NO_INDEX=1
  python -m pip check
  python "$BUNDLE_DIR/check_installation.py"
  bioemu2 propagate --help
)
echo '[5/5] Save local checkpoint location and activation instructions'
printf '%s\n' "$BUNDLE_DIR/model/checkpoint.ckpt" > "$ENV_DIR/bioemu2_checkpoint_path.txt"
printf '\nOFFLINE_INSTALL_CPU_OK\nActivate:\nconda activate "%s"\n' "$ENV_DIR"
printf 'Checkpoint: %s/model/checkpoint.ckpt\n' "$BUNDLE_DIR"
echo 'Keep the bundle/model directory. GPU/model loading/propagation are still unverified.'
