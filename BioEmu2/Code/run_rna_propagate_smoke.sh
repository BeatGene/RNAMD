#!/usr/bin/env bash
set -euo pipefail
if [[ $# -lt 1 || $# -gt 2 ]]; then
  echo 'Usage: bash run_rna_propagate_smoke.sh ALLOCATED_GPU_ID [CONDA_ENV_PREFIX]' >&2
  exit 2
fi
BIOEMU2_GPU="$1"
BIOEMU2_ENV="${2:-$HOME/miniconda3/envs/bioemu2}"
case "$BIOEMU2_GPU" in
  ''|*,*) echo 'Select exactly one allocated GPU index or GPU UUID.' >&2; exit 2 ;;
esac
CODE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
[[ -x "$BIOEMU2_ENV/bin/python" ]] || { echo "Python not found: $BIOEMU2_ENV/bin/python" >&2; exit 1; }
[[ -f "$CODE_DIR/smoke_propagate_rna.py" ]] || { echo 'Upload smoke_propagate_rna.py beside this launcher.' >&2; exit 1; }
ROOT="${BIOEMU2_SMOKE_ROOT:-$HOME/bioemu2_setup/propagate_smoke}"
mkdir -p "$ROOT"
RUN_DIR="$(mktemp -d "$ROOT/run_$(date +%Y%m%d_%H%M%S)_XXXXXX")"
LOG="$RUN_DIR/run.log"

# Put first-use compiler caches on the writable overlay, rather than slow NFS.
LOCAL_CACHE="/var/tmp/bioemu2-smoke-$(id -u)"
if [[ -L "$LOCAL_CACHE" ]]; then
  echo "Refusing symlink cache directory: $LOCAL_CACHE" >&2; exit 1
fi
if [[ ! -d "$LOCAL_CACHE" ]]; then mkdir -m 700 "$LOCAL_CACHE"; fi
[[ -O "$LOCAL_CACHE" && -w "$LOCAL_CACHE" ]] || { echo "Cache directory not owned/writable: $LOCAL_CACHE" >&2; exit 1; }
mkdir -p "$LOCAL_CACHE/triton" "$LOCAL_CACHE/cuda" "$LOCAL_CACHE/tmp"
unset PYTHONPATH PYTHONHOME
export PATH="$BIOEMU2_ENV/bin:$PATH"
export CUDA_VISIBLE_DEVICES="$BIOEMU2_GPU"
export HF_HUB_OFFLINE=1
export TRITON_CACHE_DIR="$LOCAL_CACHE/triton"
export CUDA_CACHE_PATH="$LOCAL_CACHE/cuda"
export TMPDIR="$LOCAL_CACHE/tmp"
export OMP_NUM_THREADS=2
export OPENBLAS_NUM_THREADS=2

nohup bash -c '
  "$1" -I -u "$2" --out "$3"
  bioemu2_exit_code=$?
  printf "\nSMOKE_EXIT_CODE=%s\n" "$bioemu2_exit_code"
  exit "$bioemu2_exit_code"
' _ "$BIOEMU2_ENV/bin/python" "$CODE_DIR/smoke_propagate_rna.py" "$RUN_DIR/results" \
  > "$LOG" 2>&1 < /dev/null &
BIOEMU2_PID=$!
printf '%s\n' "$BIOEMU2_PID" > "$RUN_DIR/run.pid"
printf '%s\n' "$BIOEMU2_ENV" > "$RUN_DIR/env_prefix.txt"
printf '%s\n' "$RUN_DIR" > "$ROOT/latest_run_path.txt"
printf 'PID: %s\nGPU selection: %s\nRun directory: %s\nLog: %s\n' \
  "$BIOEMU2_PID" "$BIOEMU2_GPU" "$RUN_DIR" "$LOG"
echo 'Background launch requested; success requires RNA_PROPAGATE_SMOKE_OK and SMOKE_EXIT_CODE=0 in the log.'
