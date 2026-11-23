#!/usr/bin/env bash
# Sourced only by this setup bundle; does not activate or modify environments.
find_setup_conda() {
  local candidate
  for candidate in "${CONDA_EXE:-}" "$(type -P conda || true)" \
    "$HOME/miniconda3/bin/conda" "$HOME/anaconda3/bin/conda" \
    "$HOME/miniforge3/bin/conda"; do
    if [[ -n "$candidate" && -x "$candidate" ]]; then
      SETUP_CONDA="$candidate"
      return 0
    fi
  done
  echo 'Conda executable not found. Run conda activate base in this shell and retry.' >&2
  return 1
}
