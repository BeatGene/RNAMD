#!/usr/bin/env bash
# Reuse the offline bundle; restart interrupted installation in fresh paths.
# Arguments: [--reuse-names] [bundle_dir] [preferred_env_prefix] [preferred_source_dir] [log_root]
set -euo pipefail
REUSE_NAMES=false
if [[ "${1:-}" == --reuse-names ]]; then
  REUSE_NAMES=true
  shift
fi
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUNDLE="$(cd "${1:-$SCRIPT_DIR/bundle}" && pwd)"
ENV_PREFIX="${2:-$HOME/miniconda3/envs/dynarna}"
SOURCE_DIR="${3:-$HOME/Code/DynaRNA}"
LOG_ROOT="${4:-$SCRIPT_DIR/install_logs}"
[[ "$ENV_PREFIX" == /* && "$SOURCE_DIR" == /* && "$LOG_ROOT" == /* ]] || {
  echo 'Environment, source and log paths must be absolute.' >&2; exit 1;
}
[[ -f "$BUNDLE/install_offline_server.sh" && -f "$BUNDLE/SHA256SUMS" ]] || {
  echo 'Missing installer or SHA256SUMS in bundle directory.' >&2; exit 1;
}
command -v flock >/dev/null || { echo 'flock is required for the background installation lock.' >&2; exit 1; }
PROCESS_PYTHON="$(command -v python3 || true)"
if [[ -z "$PROCESS_PYTHON" && -x "$HOME/miniconda3/bin/python" ]]; then
  PROCESS_PYTHON="$HOME/miniconda3/bin/python"
fi
[[ -n "$PROCESS_PYTHON" ]] || { echo 'Python is required for the read-only process check.' >&2; exit 1; }
mkdir -p "$LOG_ROOT"
exec 9>"$LOG_ROOT/install.lock"
flock -n 9 || { echo 'A background installation already holds the lock; inspect install_logs.' >&2; exit 1; }
# Only inspect processes tied to this bundle/environment/source. A generic
# sha256sum or install_offline_server.sh may belong to BioEmu2, not DynaRNA.
"$PROCESS_PYTHON" - "$BUNDLE" "$ENV_PREFIX" "$SOURCE_DIR" <<'PY'
import os
from pathlib import Path
import sys


def within(path, root):
    return path == root or root in path.parents


def scan(proc, roots, excluded, uid):
    active = []
    errors = []
    for entry in proc.iterdir():
        if not entry.name.isdigit() or int(entry.name) in excluded:
            continue
        try:
            if entry.stat().st_uid != uid:
                continue
            args = (entry / 'cmdline').read_bytes().split(b'\0')
            args = [os.fsdecode(arg) for arg in args if arg]
            if not args:
                continue
            cwd = (entry / 'cwd').resolve(strict=True)
            argument_paths = []
            for arg in args:
                value = arg.split('=', 1)[-1] if '=' in arg else arg
                if value.startswith('/'):
                    argument_paths.append(Path(value).resolve())
                elif '/' in value and not any(c.isspace() for c in value):
                    argument_paths.append((cwd / value).resolve())
            if any(within(path, root) for path in [cwd, *argument_paths] for root in roots):
                active.append((entry.name, ' '.join(args)[:400], str(cwd)))
        except (FileNotFoundError, ProcessLookupError):
            continue  # A process can exit while /proc is being inspected.
        except OSError as exc:
            errors.append((entry.name, type(exc).__name__))
    return active, errors


def main():
    proc = Path('/proc')
    if not proc.is_dir():
        raise SystemExit('Linux /proc is required; no installation started.')
    # Exclude this probe and its ancestor shells, whose positional arguments
    # may contain the very installation paths being checked.
    excluded = set()
    pid = os.getpid()
    while pid > 0 and pid not in excluded:
        excluded.add(pid)
        try:
            fields = (proc / str(pid) / 'stat').read_text().rsplit(')', 1)[1].split()
            pid = int(fields[1])
        except (OSError, ValueError, IndexError):
            break
    roots = [Path(value).resolve() for value in sys.argv[1:]]
    active, errors = scan(proc, roots, excluded, os.getuid())
    if active:
        for pid, args, cwd in active:
            print('ACTIVE DynaRNA process:', pid, args, '[cwd=' + cwd + ']')
        raise SystemExit('DynaRNA files may still be in use; no new installation started.')
    if errors:
        print('Could not inspect owned processes:', errors[:10])
        raise SystemExit('Process check incomplete; no installation started.')
    print('No running processes tied to these DynaRNA paths were found.')


if __name__ == '__main__':
    main()
PY
RUN_ID="$(date +%Y%m%d_%H%M%S)_$$"
RUN_DIR="$LOG_ROOT/$RUN_ID"
mkdir "$RUN_DIR"
if [[ "$REUSE_NAMES" == true ]]; then
  # Renaming is reversible and retains the original bytes. Backup environments
  # are archives of the interrupted state, not validated activatable environments.
  for ORIGINAL in "$ENV_PREFIX" "$SOURCE_DIR"; do
    if [[ -e "$ORIGINAL" || -L "$ORIGINAL" ]]; then
      BACKUP="${ORIGINAL}.interrupted_${RUN_ID}"
      [[ ! -e "$BACKUP" && ! -L "$BACKUP" ]] || { echo 'Backup path exists.' >&2; exit 1; }
      printf 'ORIGINAL=%s\nBACKUP=%s\n' "$ORIGINAL" "$BACKUP" >> "$RUN_DIR/backups.txt"
      mv -- "$ORIGINAL" "$BACKUP"
      printf 'Preserved interrupted directory: %s\n' "$BACKUP"
    fi
  done
elif [[ -e "$ENV_PREFIX" || -e "$SOURCE_DIR" ]]; then
  ENV_PREFIX="${ENV_PREFIX}_recover_${RUN_ID}"
  SOURCE_DIR="${SOURCE_DIR}_recover_${RUN_ID}"
  echo 'Existing paths are preserved. Restarting installation in new paths.'
fi
[[ ! -e "$ENV_PREFIX" && ! -e "$SOURCE_DIR" ]] || { echo 'Recovery destination already exists.' >&2; exit 1; }
printf 'ENV_PREFIX=%s\nSOURCE_DIR=%s\nBUNDLE=%s\n' "$ENV_PREFIX" "$SOURCE_DIR" "$BUNDLE" > "$RUN_DIR/paths.txt"
# The detached child inherits fd 9, keeping the lock until installation ends.
# Explicit arguments avoid interpolating paths into shell program text.
nohup bash -c '
  if bash "$1" "$2" "$3"; then
    install_status=0
  else
    install_status=$?
  fi
  printf "%s\n" "$install_status" > "$4"
  printf "\nINSTALL_EXIT_CODE=%s\n" "$install_status"
  exit "$install_status"
' dynarna-install "$BUNDLE/install_offline_server.sh" "$ENV_PREFIX" "$SOURCE_DIR" "$RUN_DIR/exit_code.txt" \
  > "$RUN_DIR/install.log" 2>&1 < /dev/null &
INSTALL_PID=$!
printf '%s\n' "$INSTALL_PID" > "$RUN_DIR/install.pid"
printf 'Background installer PID: %s\nEnvironment: %s\nSource: %s\nRun directory: %s\n' \
  "$INSTALL_PID" "$ENV_PREFIX" "$SOURCE_DIR" "$RUN_DIR"
printf 'Monitor: tail -f "%s/install.log"\nExit status: cat "%s/exit_code.txt"\n' "$RUN_DIR" "$RUN_DIR"
echo 'Normal SSH disconnection will not send SIGHUP to this nohup job. GPU verification is a separate next step.'
