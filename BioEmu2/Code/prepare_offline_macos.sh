#!/usr/bin/env bash
set -euo pipefail
CODE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$CODE_DIR/.." && pwd)"
RUN_ID="$(date +%Y%m%d_%H%M%S)_$$"
RUN_DIR="$PROJECT_DIR/Offline/$RUN_ID"
CONTAINER_NAME="bioemu2-offline-$RUN_ID"
mkdir -p "$RUN_DIR"
docker info >/dev/null
docker version > "$RUN_DIR/docker_version.txt"
printf '%s\n' "$CONTAINER_NAME" > "$RUN_DIR/container_name.txt"
printf 'Working directory: %s\nContainer: %s\n' "$RUN_DIR" "$CONTAINER_NAME"
printf 'Large downloads and x86 emulation may take a long time. Do not close this terminal.\n'
# Keep the container after failure so downloading/installing can be resumed.
# No host Conda installation, GPU access, privileged mode, or Docker socket mount.
docker run --platform linux/amd64 --name "$CONTAINER_NAME" \
  --mount "type=bind,source=$CODE_DIR,target=/code,readonly" \
  --mount "type=bind,source=$RUN_DIR,target=/work" \
  python:3.12-slim-bookworm \
  bash /code/build_in_container.sh 2>&1 | tee "$RUN_DIR/build.log"
docker inspect --format '{{.Image}}' "$CONTAINER_NAME" > "$RUN_DIR/docker_image_id.txt"
printf '\nBuild completed. Upload these two files:\n%s\n%s\n' \
  "$RUN_DIR/bioemu2_offline_bundle.tar" \
  "$RUN_DIR/bioemu2_offline_bundle.tar.sha256"
