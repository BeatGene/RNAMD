#!/usr/bin/env bash
set -euo pipefail
trap 'printf "INSTALL FAILED at line %s; keep the log and partial environment.\n" "$LINENO" >&2' ERR
CODE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$CODE_DIR/common.sh"
if [[ $# -ne 2 ]]; then
  echo 'Usage: bash install_online.sh /absolute/new/env/prefix CUDA_VERSION' >&2
  echo 'Choose CUDA_VERSION (e.g. 12.x) after inspecting the server driver report.' >&2
  exit 2
fi
ENV_DIR="$1"
CUDA_RELEASE="$2"
[[ "$(uname -s)" == Linux ]] || { echo 'Server installer requires Linux'; exit 1; }
[[ "$ENV_DIR" == /* && "$ENV_DIR" != *[[:space:]]* ]] || {
  echo 'Use an absolute environment path without whitespace'; exit 2;
}
[[ "$CUDA_RELEASE" =~ ^(12|13)(\.[0-9]+)?$ ]] || { echo 'Invalid CUDA version'; exit 2; }
if [[ -e "$ENV_DIR" || -L "$ENV_DIR" ]]; then
  echo "Refusing to overwrite existing environment/path: $ENV_DIR" >&2; exit 1
fi
find_setup_conda
# Conda detects driver constraints itself. Never fake __cuda or disable TLS.
[[ -z "${CONDA_OVERRIDE_CUDA:-}" && -z "${CONDA_SUBDIR:-}" ]] || {
  echo 'Unset CONDA_OVERRIDE_CUDA and CONDA_SUBDIR before native server installation.' >&2; exit 1;
}
LOG_ROOT="${RNA_MD_LOG_ROOT:-$HOME/openmm_rna_setup/install_logs}"
mkdir -p "$LOG_ROOT"
LOG_DIR="$(mktemp -d "$LOG_ROOT/online_$(date +%Y%m%d_%H%M%S)_XXXXXX")"
exec > >(tee "$LOG_DIR/install.log") 2>&1
echo "Log: $LOG_DIR/install.log"
echo "New environment: $ENV_DIR; requested CUDA: $CUDA_RELEASE"
export CONDA_REMOTE_CONNECT_TIMEOUT_SECS=15
export CONDA_REMOTE_READ_TIMEOUT_SECS=45
export CONDA_REMOTE_MAX_RETRIES=1
unset PYTHONPATH PYTHONHOME
"$SETUP_CONDA" create --prefix "$ENV_DIR" --override-channels \
  -c conda-forge --strict-channel-priority -y \
  'python=3.11' 'openmm>=8.2,<9' 'ambertools>=24,<27' \
  'parmed>=4,<5' mdtraj numpy "cuda-version=$CUDA_RELEASE"
"$SETUP_CONDA" list -p "$ENV_DIR" --explicit > "$LOG_DIR/conda-explicit.txt"
"$SETUP_CONDA" env export -p "$ENV_DIR" > "$LOG_DIR/environment-resolved.yml"
# Inventory does not create a GPU context or start MD.
"$SETUP_CONDA" run --no-capture-output -p "$ENV_DIR" \
  python "$CODE_DIR/check_environment.py" --platform inventory --output-root "$LOG_DIR/checks"
echo 'RNA_MD_ENV_INSTALLED_INVENTORY_OK'
echo 'CPU RNA smoke and CUDA RNA smoke are still required; see INSTALL_SERVER.md.'
printf 'Activate: conda activate "%s"\n' "$ENV_DIR"
