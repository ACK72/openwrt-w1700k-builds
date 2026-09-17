#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-2.0-only
set -Eeuo pipefail
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
# apt-cache depends --installed follows build dependencies without including
# unrelated preinstalled Android/.NET/browser packages in the cache identity.
mapfile -t packages < "$ROOT/configs/build-packages.txt"
# shellcheck disable=SC2016 # dpkg-query expands these placeholders, not Bash.
{
    cat /etc/os-release
    uname -m
    apt-cache depends --recurse --installed --no-recommends --no-suggests \
        --no-conflicts --no-breaks --no-replaces --no-enhances "${packages[@]}" |
        awk '/^[a-zA-Z0-9][^ <>]*$/ {print $1}' | sort -u |
        xargs -r dpkg-query -W '-f=${binary:Package}=${Version}\n' | sort
} | sha256sum | cut -d' ' -f1
