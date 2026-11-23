#!/usr/bin/env bash
set -euo pipefail
CODE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$CODE_DIR/.." && pwd)"
docker info >/dev/null
RUN_ID="$(date +%Y%m%d_%H%M%S)_$$"
RUN_DIR="$PROJECT_DIR/Offline/$RUN_ID"
CONTAINER_NAME="dynarna-offline-$RUN_ID"
mkdir -p "$RUN_DIR"
docker version > "$RUN_DIR/docker_version.txt"
printf '%s\n' "$CONTAINER_NAME" > "$RUN_DIR/container_name.txt"
printf 'Build directory: %s\nContainer: %s\n' "$RUN_DIR" "$CONTAINER_NAME"
# Keep the container and downloaded files on success or failure. No GPU,
# privileged mode, Docker socket mount, or host conda installation is used.
docker run --platform linux/amd64 --name "$CONTAINER_NAME" \
  --mount "type=bind,source=$CODE_DIR,target=/code,readonly" \
  --mount "type=bind,source=$RUN_DIR,target=/work" \
  python:3.10-slim-bookworm \
  bash /code/build_in_container.sh 2>&1 | tee "$RUN_DIR/build.log"
docker inspect --format '{{.Image}}' "$CONTAINER_NAME" > "$RUN_DIR/docker_image_id.txt"
printf '\nUpload these files:\n%s\n%s\n' \
  "$RUN_DIR/dynarna_offline_bundle.tar" "$RUN_DIR/dynarna_offline_bundle.tar.sha256"

