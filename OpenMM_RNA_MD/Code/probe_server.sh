#!/usr/bin/env bash
set -euo pipefail
CODE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$CODE_DIR/common.sh"
SETUP_CONDA=''
find_setup_conda || true
SETUP_PYTHON="$(type -P python3 || type -P python || true)"
if [[ -z "$SETUP_PYTHON" && -n "$SETUP_CONDA" ]]; then
  SETUP_PYTHON="$(dirname "$SETUP_CONDA")/python"
fi
[[ -n "$SETUP_PYTHON" && -x "$SETUP_PYTHON" ]] || {
  echo 'No Python found. Activate an existing Conda environment and retry.' >&2; exit 1;
}
exec env -u PYTHONPATH -u PYTHONHOME "$SETUP_PYTHON" \
  "$CODE_DIR/probe_server.py" --conda-exe "$SETUP_CONDA" "$@"
