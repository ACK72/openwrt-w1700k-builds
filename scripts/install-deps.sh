#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-2.0-only
set -Eeuo pipefail
# shellcheck source=/dev/null
. /etc/os-release
[[ $ID == ubuntu && $VERSION_ID == 24.04 ]] || { echo 'Ubuntu 24.04 is required' >&2; exit 1; }
sudo apt-get update
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
mapfile -t packages < "$ROOT/configs/build-packages.txt"
sudo apt-get install -y --no-install-recommends "${packages[@]}"
