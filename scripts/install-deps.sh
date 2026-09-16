#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-2.0-only
set -Eeuo pipefail
# shellcheck source=/dev/null
. /etc/os-release
[[ $ID == ubuntu && $VERSION_ID == 24.04 ]] || { echo 'Ubuntu 24.04 is required' >&2; exit 1; }
sudo apt-get update
sudo apt-get install -y --no-install-recommends \
    build-essential clang-18 lld-18 llvm-18 llvm-18-dev \
    bison flex gawk gettext git gperf help2man \
    libelf-dev libncurses-dev libssl-dev libtool-bin \
    autoconf automake cmake ninja-build pkgconf \
    python3 python3-setuptools python3-pyelftools python3-dev \
    rsync swig unzip zlib1g-dev zstd file wget curl ca-certificates \
    patch perl time bzip2 xz-utils tar gzip
