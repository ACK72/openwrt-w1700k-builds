#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-2.0-only
set -Eeuo pipefail
shopt -s inherit_errexit
umask 022
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
WORK="$ROOT/.work"
CACHE="$ROOT/.cache"
OPENWRT="$WORK/openwrt"
NPU="$WORK/npu"
OUT="$ROOT/artifacts"
LOGS="$ROOT/logs"
OPENWRT_REPO=${OPENWRT_REPO:-https://github.com/ACK72/openwrt.git}
OPENWRT_REF=${OPENWRT_REF:-ubi2-oc}
NPU_REPO=${NPU_REPO:-https://github.com/ACK72/airoha-npu-fdk.git}
NPU_REF=${NPU_REF:-main}
CONFIG_FILE=${CONFIG_FILE:-$ROOT/configs/w1700k.config}
export CCACHE_COMPILERCHECK=content
export CCACHE_MAXSIZE=${CCACHE_MAXSIZE:-3G}
export CCACHE_DIR="$CACHE/ccache"
export CCACHE_BASEDIR="$OPENWRT"
export CCACHE_COMPRESS=true
export CCACHE_COMPRESSLEVEL=1
# Keep ccache's correctness checks; no time_macros/file_stat_matches sloppiness.
export LLVM_CC=clang-18 LLVM_OBJCOPY=llvm-objcopy-18
export LLVM_READOBJ=llvm-readobj-18 LLVM_AR=llvm-ar-18
# OpenWrt otherwise prints recursive Kconfig errors but exits successfully.
export RECURSIVE_DEP_IS_ERROR=1

die() { echo "ERROR: $*" >&2; exit 1; }
[[ $(uname -s) == Linux ]] || die 'Use Ubuntu 24.04, a Linux VM, or WSL2 on an ext4 filesystem.'
[[ $ROOT != *' '* ]] || die 'OpenWrt requires a workspace path without spaces.'
mkdir -p "$WORK" "$CACHE" "$OUT" "$LOGS" "$CCACHE_DIR"

# RAM-limited parallelism avoids expensive OOM failures on hosted runners.
cpu_jobs=$(nproc)
ram_jobs=$(awk '/MemAvailable:/ { n=int(($2-1572864)/1048576); print (n>0?n:1) }' /proc/meminfo)
default_jobs=$((cpu_jobs < ram_jobs ? cpu_jobs : ram_jobs))
JOBS=${JOBS:-$default_jobs}
DOWNLOAD_JOBS=${DOWNLOAD_JOBS:-8}
[[ $JOBS =~ ^[1-9][0-9]*$ && $DOWNLOAD_JOBS =~ ^[1-9][0-9]*$ ]] || die 'Job counts must be positive integers.'

checkout_source() {
    local url=$1 ref=$2 dest=$3 history=${4:-shallow}
    local fetch_args=(--depth=1)
    [[ $ref != -* && -n $ref ]] || die 'Invalid source ref'
    if [[ ! -d $dest/.git ]]; then
        [[ ! -e $dest ]] || die "Refusing to replace unmanaged path: $dest"
        git init "$dest"
        git -C "$dest" remote add origin "$url"
        touch "$dest/.git/managed-by-w1700k-builder"
    fi
    [[ -f $dest/.git/managed-by-w1700k-builder ]] || die "Unmanaged checkout: $dest"
    git -C "$dest" remote set-url origin "$url"
    if [[ $history == full ]]; then
        # getver.sh needs the reboot ancestor and an upstream branch to count
        # revisions correctly. Omit historical blobs, not commit history.
        fetch_args=(--filter=blob:none --no-tags)
        if [[ $(git -C "$dest" rev-parse --is-shallow-repository) == true ]]; then
            fetch_args+=(--unshallow)
        fi
    fi
    git -C "$dest" -c core.autocrlf=false fetch "${fetch_args[@]}" origin "$ref"
    # Only this builder's disposable .work checkout is reset, never a sibling repo.
    git -C "$dest" -c core.autocrlf=false checkout --detach --force FETCH_HEAD
    if [[ $history == full ]]; then
        git -C "$dest" update-ref refs/remotes/origin/build-source HEAD
        git -C "$dest" checkout -B builder
        git -C "$dest" branch --set-upstream-to=origin/build-source builder
    fi
}

npu_key() {
    {
        git -C "$NPU" rev-parse HEAD
        for tool in clang-18 ld.lld-18 llvm-objcopy-18 llvm-readobj-18 llvm-ar-18; do
            "$tool" --version
            sha256sum "$(command -v "$tool")"
        done
        sha256sum "$ROOT/scripts/build.sh" "$ROOT/scripts/build-meta.py"
        find "$ROOT/patches/npu" -type f -name '*.patch' -print0 | sort -z | xargs -0 sha256sum
        uname -m
    } | sha256sum | cut -d' ' -f1
}

prepare() {
    local key
    checkout_source "$OPENWRT_REPO" "$OPENWRT_REF" "$OPENWRT" full
    checkout_source "$NPU_REPO" "$NPU_REF" "$NPU"
    for patch_file in "$ROOT"/patches/npu/*.patch; do
        if git -C "$NPU" apply --check "$patch_file"; then
            git -C "$NPU" apply "$patch_file"
        elif git -C "$NPU" apply --reverse --check "$patch_file"; then
            echo "Already included upstream: ${patch_file##*/}"
        else
            die "FDK compatibility patch no longer applies: $patch_file"
        fi
    done
    mkdir -p "$CACHE/dl" "$CACHE/npu"
    if [[ -L $OPENWRT/dl ]]; then
        [[ $(readlink -f "$OPENWRT/dl") == "$CACHE/dl" ]] || die 'Unexpected dl symlink'
    elif [[ -e $OPENWRT/dl ]]; then
        die 'Managed dl must be a cache symlink'
    else
        ln -s "$CACHE/dl" "$OPENWRT/dl"
    fi
    key=$(npu_key)
    {
        echo "openwrt=$(git -C "$OPENWRT" rev-parse HEAD)"
        echo "npu=$(git -C "$NPU" rev-parse HEAD)"
        echo "npu-key=$key"
    } | tee "$WORK/sources.env"
}

build_npu() {
    local key
    key=$(npu_key)
    if [[ -f $CACHE/npu/source-key && $(cat "$CACHE/npu/source-key") == "$key" ]] &&
       [[ -s $CACHE/npu/debug/firmware.elf && -s $CACHE/npu/debug/firmware.map ]] &&
       (cd "$CACHE/npu" && sha256sum -c SHA256SUMS); then
        echo 'Using verified NPU firmware cache'
    else
        python3 "$NPU/airoha-npu-fdk-build" --platform an7581 \
            -o "$CACHE/npu/en7581_MT7996_npu" \
            --debug-directory "$CACHE/npu/debug" 2>&1 | tee "$LOGS/npu.log"
        (cd "$CACHE/npu" && sha256sum en7581_MT7996_npu_{rv32,data}.bin \
            debug/firmware.{elf,map} > SHA256SUMS)
        printf '%s\n' "$key" > "$CACHE/npu/source-key"
    fi
    python3 "$ROOT/scripts/build-meta.py" install-npu "$OPENWRT" "$NPU" "$CACHE/npu"
}

configure() {
    local profile feeds_file
    local feed_packages=()
    # Resolve caller-supplied relative paths before entering the source tree.
    profile=$(realpath -e -- "$CONFIG_FILE")
    feeds_file=$(realpath -e -- "${FEEDS_LOCK:-$OPENWRT/feeds.conf.default}")
    cd "$OPENWRT"
    # An optional lock uses normal src-git name URL^FULL_COMMIT lines.
    cp "$feeds_file" feeds.conf
    ./scripts/feeds update -a 2>&1 | tee "$LOGS/feeds-update.log"
    # Keep exact feed revisions even when installation or defconfig fails.
    ./scripts/feeds list -s -f > "$WORK/feeds.lock"
    ./scripts/feeds uninstall -a 2>&1 | tee "$LOGS/feeds-uninstall.log"
    make -s prepare-tmpinfo 2>&1 | tee "$LOGS/package-metadata.log"
    # Unselected feed recipes can have broken Kconfig dependencies. Register
    # device defaults and requested packages; feeds resolves their dependencies.
    python3 "$ROOT/scripts/build-meta.py" feed-packages "$OPENWRT" "$profile" > "$WORK/feed-packages.txt"
    mapfile -t feed_packages < "$WORK/feed-packages.txt"
    (( ${#feed_packages[@]} > 0 )) || die 'No firmware packages selected'
    ./scripts/feeds install "${feed_packages[@]}" 2>&1 | tee "$LOGS/feeds-install.log"
    cp "$profile" .config
    printf 'CONFIG_CCACHE_DIR="%s"\n' "$CCACHE_DIR" >> .config
    # Validate Kconfig against the effective request, including builder overrides.
    cp .config "$WORK/requested.config"
    make defconfig 2>&1 | tee "$LOGS/defconfig.log"
    python3 "$ROOT/scripts/build-meta.py" check-config "$OPENWRT" "$WORK/requested.config"
    python3 "$ROOT/scripts/build-meta.py" keys "$OPENWRT" "$NPU" | tee "$WORK/keys.env"
}

run_make() {
    local name=$1
    shift
    local start=$SECONDS status=0
    make -C "$OPENWRT" -j"$JOBS" "$@" 2>&1 | tee "$LOGS/$name.log" || status=$?
    printf '%s\t%s\t%s\n' "$name" "$((SECONDS-start))" "$status" >> "$LOGS/timings.tsv"
    return "$status"
}

restore_build() {
    local kind key
    rm -f "$WORK/cache-restored"
    for kind in build toolchain; do
        key=$(sed -n "s/^${kind}=//p" "$WORK/keys.env")
        [[ $key =~ ^[a-f0-9]{64}$ ]] || die 'Run configure before restoring build state'
        python3 "$ROOT/scripts/build-cache.py" restore "$kind" "$OPENWRT" "$CACHE/$kind" "$key"
        [[ ! -f $WORK/cache-restored ]] || break
    done
}

save_build() {
    local kind=${1:-build} key
    key=$(sed -n "s/^${kind}=//p" "$WORK/keys.env")
    [[ $key =~ ^[a-f0-9]{64}$ ]] || die 'Run configure before saving build state'
    python3 "$ROOT/scripts/build-cache.py" save "$kind" "$OPENWRT" "$CACHE/$kind" "$key"
}

download() {
    make -C "$OPENWRT" -j"$DOWNLOAD_JOBS" download 2>&1 | tee "$LOGS/download.log"
}

toolchain() {
    if [[ -f $WORK/cache-restored ]]; then
        echo "Using compatible $(cat "$WORK/cache-restored") snapshot; tools will still be dependency-checked by make."
        return
    fi
    run_make tools tools/install
    run_make toolchain toolchain/install
    save_build toolchain
}

compile() {
    # Cached package stamps are reusable; previously emitted images/APKs are not.
    # This path is always the builder-owned .work checkout, never a sibling repo.
    [[ ! -L $OPENWRT/bin ]] || die 'Unexpected output directory symlink'
    rm -rf -- "${OPENWRT:?}/bin"
    # Cached statistics otherwise include previous runs. Report this firmware
    # compilation separately from the initial tools/toolchain build.
    if [[ -x $OPENWRT/staging_dir/host/bin/ccache ]]; then
        "$OPENWRT/staging_dir/host/bin/ccache" -z > "$LOGS/ccache-reset.log" 2>&1 || true
    fi
    if [[ -f $WORK/cache-restored && $(cat "$WORK/cache-restored") == build ]]; then
        # Regenerate release identity and the public package key for this run.
        run_make base-files-clean package/base-files/clean
    fi
    if ! run_make build; then
        echo 'Parallel build failed; retrying once with one job and full diagnostics.' >&2
        make -C "$OPENWRT" -j1 V=s 2>&1 | tee "$LOGS/build-retry.log"
    fi
    if ! "$OPENWRT/staging_dir/host/bin/ccache" -s 2>&1 | tee "$LOGS/ccache.log"; then
        echo 'WARNING: Could not collect ccache statistics; firmware compilation succeeded.' >&2
    fi
}

collect() {
    local target="$OPENWRT/bin/targets/airoha/an7581"
    shopt -s nullglob
    images=("$target"/*gemtek_w1700k-ubi*sysupgrade.itb)
    (( ${#images[@]} == 1 )) || die 'Expected exactly one W1700K sysupgrade image'
    python3 "$ROOT/scripts/build-meta.py" check-installed "$OPENWRT"
    "$OPENWRT/staging_dir/host/bin/fwtool" -i "$WORK/image-metadata.json" "${images[0]}"
    python3 "$ROOT/scripts/release.py" verify-image "$target" "$WORK/image-metadata.json"
    # Output is owned by this script, but preserve old runs in separate directories.
    local dest fingerprint
    fingerprint=$(sed -n 's/^fingerprint=//p' "$WORK/keys.env")
    [[ $fingerprint =~ ^[a-f0-9]{64}$ ]] || die 'Run configure before collect'
    dest="$OUT/$fingerprint"
    mkdir -p "$dest/firmware" "$dest/npu"
    find "$target" -maxdepth 1 -type f -exec cp -t "$dest/firmware" {} +
    cp "$OPENWRT/.config" "$dest/openwrt.config"
    cp "$WORK/feeds.lock" "$dest/feeds.lock"
    cp "$WORK/image-metadata.json" "$dest/image-metadata.json"
    cp "$OPENWRT/public-key.pem" "$dest/public-key.pem"
    "$OPENWRT/scripts/diffconfig.sh" > "$dest/config.diff"
    cp "$CACHE/npu/"*.bin "$dest/npu/"
    cp "$NPU/LICENSE" "$dest/npu/LICENSE"
    cp -r "$CACHE/npu/debug" "$dest/npu/"
    python3 "$ROOT/scripts/build-meta.py" manifest "$OPENWRT" "$NPU" "$dest"
    # Packages selected with =y are already installed in the image rootfs.
    # Keep diagnostics in the Actions artifact; releases publish only the ITB.
    # SHA256SUMS itself is explicitly excluded from the input file list.
    # shellcheck disable=SC2094
    (cd "$dest" && find . -type f ! -name SHA256SUMS -print0 | sort -z | xargs -0 sha256sum > SHA256SUMS)
    printf '%s\n' "$dest" > "$WORK/artifact-path"
}

case ${1:-all} in
    prepare) prepare ;;
    npu) build_npu ;;
    configure) configure ;;
    restore) restore_build ;;
    snapshot) save_build build ;;
    download) download ;;
    toolchain) toolchain ;;
    compile) compile ;;
    collect) cd "$OPENWRT"; collect ;;
    all) prepare; build_npu; configure; restore_build; download; toolchain; compile; cd "$OPENWRT"; collect; save_build build ;;
    *) die 'Usage: bash scripts/build.sh [all|prepare|npu|configure|restore|download|toolchain|compile|collect|snapshot]' ;;
esac
