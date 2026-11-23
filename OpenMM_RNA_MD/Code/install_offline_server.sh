#!/usr/bin/env bash
set -euo pipefail
trap 'printf "OFFLINE INSTALL FAILED at line %s; keep log and partial environment.\n" "$LINENO" >&2' ERR
BUNDLE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_DIR="${1:-$HOME/miniconda3/envs/openmm_rna_ol3}"
[[ "$(uname -s)/$(uname -m)" == Linux/x86_64 ]] || { echo 'Requires Linux x86_64'; exit 1; }
[[ "$ENV_DIR" == /* && "$ENV_DIR" != *[[:space:]]* ]] || { echo 'Use absolute prefix without whitespace'; exit 2; }
if [[ -e "$ENV_DIR" || -L "$ENV_DIR" ]]; then
  echo "Refusing to overwrite existing path: $ENV_DIR" >&2; exit 1
fi
LOG_ROOT="$HOME/openmm_rna_setup/install_logs"
mkdir -p "$LOG_ROOT"
LOG_DIR="$(mktemp -d "$LOG_ROOT/offline_$(date +%Y%m%d_%H%M%S)_XXXXXX")"
exec > >(tee "$LOG_DIR/install.log") 2>&1
echo "Log: $LOG_DIR/install.log"
cd "$BUNDLE_DIR"
echo "[$(date -Is)] [1/4] Verify bundle hashes"
sha256sum -c SHA256SUMS
echo "[$(date -Is)] [2/4] Extract environment into $ENV_DIR (shared storage may be slow)"
mkdir -p "$ENV_DIR"
tar --checkpoint=10000 --checkpoint-action=echo='extracting checkpoint %u' \
  -xzf rna_env_linux_x86_64.tar.gz -C "$ENV_DIR"
echo "[$(date -Is)] [2/4] Extraction complete"
unset PYTHONPATH PYTHONHOME AMBERHOME OPENMM_PLUGIN_DIR CONDA_OVERRIDE_CUDA
# Use the packed Python explicitly: conda-unpack's shebang still names the builder.
echo "[$(date -Is)] [3/4] Repair relocated prefixes (conda-unpack)"
"$ENV_DIR/bin/python" -u "$ENV_DIR/bin/conda-unpack"
echo "[$(date -Is)] [3/4] Prefix repair complete"
echo "[$(date -Is)] [4/4] Run CPU RNA smoke"
(
  # conda-pack's activate probes `type deactivate` and references PS1. It is
  # not safe under `set -eu` when a modern Conda environment is already active.
  # Use this prefix directly; the checker resolves tools via sys.prefix and
  # supplies AMBERHOME to tleap. No inherited activation hooks are needed.
  export PATH="$ENV_DIR/bin:$PATH" CONDA_PREFIX="$ENV_DIR" AMBERHOME="$ENV_DIR"
  export CUDA_VISIBLE_DEVICES='' OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2
  "$ENV_DIR/bin/python" -u "$BUNDLE_DIR/check_environment.py" --platform CPU --output-root "$LOG_DIR/checks"
)
echo 'RNA_MD_OFFLINE_INSTALL_CPU_OK'
printf 'Environment: %s\n' "$ENV_DIR"
echo 'CUDA RNA smoke on one authorized GPU is still required; see OFFLINE_STEPS.md.'
