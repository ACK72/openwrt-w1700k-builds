#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-2.0-only
set -Eeuo pipefail
shopt -s inherit_errexit
umask 022
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
WORK="$ROOT/.work"
CACHE="$ROOT/.cache"
OPENWRT="$WORK/openwrt"
OUT="$ROOT/artifacts"
LOGS="$ROOT/logs"
OPENWRT_REPO=${OPENWRT_REPO:-}
OPENWRT_REF=${OPENWRT_REF:-w1700k-oc-rc}
CONFIG_FILE=${CONFIG_FILE:-$ROOT/configs/w1700k.config}
export CCACHE_COMPILERCHECK=content
export CCACHE_MAXSIZE=${CCACHE_MAXSIZE:-3G}
export CCACHE_DIR="$CACHE/ccache"
export CCACHE_BASEDIR="$OPENWRT"
export CCACHE_COMPRESS=true
export CCACHE_COMPRESSLEVEL=1
# Keep ccache's correctness checks; no time_macros/file_stat_matches sloppiness.
# OpenWrt otherwise prints recursive Kconfig errors but exits successfully.
export RECURSIVE_DEP_IS_ERROR=1

die() { echo "ERROR: $*" >&2; exit 1; }
[[ $(uname -s) == Linux ]] || die 'Use Ubuntu 24.04, a Linux VM, or WSL2 on an ext4 filesystem.'
if [[ ${GITHUB_ACTIONS:-false} == true ]]; then
    [[ $(uname -m) == aarch64 ]] || die 'CI builds require an ARM64 host.'
fi
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

prepare() {
    OPENWRT_REPO=${OPENWRT_REPO:-$(python3 "$ROOT/scripts/repositories.py" openwrt)}
    checkout_source "$OPENWRT_REPO" "$OPENWRT_REF" "$OPENWRT" full
    python3 "$ROOT/scripts/official_npu.py" check "$OPENWRT"
    # Preserve fast ccache compression independently of the firmware provider.
    sed -i 's/export CCACHE_NOCOMPRESS:=true/export CCACHE_COMPRESS:=true/' "$OPENWRT/rules.mk"
    mkdir -p "$CACHE/dl"
    if [[ -L $OPENWRT/dl ]]; then
        [[ $(readlink -f "$OPENWRT/dl") == "$CACHE/dl" ]] || die 'Unexpected dl symlink'
    elif [[ -e $OPENWRT/dl ]]; then
        die 'Managed dl must be a cache symlink'
    else
        ln -s "$CACHE/dl" "$OPENWRT/dl"
    fi
    {
        echo "openwrt=$(git -C "$OPENWRT" rev-parse HEAD)"
        echo "npu=linux-firmware"
    } | tee "$WORK/sources.env"
}

distfeeds() {
    python3 "$ROOT/scripts/distfeeds.py" resolve "$WORK/distfeeds-source.json"
    python3 "$ROOT/scripts/distfeeds.py" prepare "$WORK/distfeeds-source.json" "$CACHE/distfeeds"
}

configure() {
    local profile feeds_file
    local feed_packages=()
    if [[ -n ${GOLANG_BOOTSTRAP_ROOT:-} ]]; then
        [[ $GOLANG_BOOTSTRAP_ROOT == /* && $GOLANG_BOOTSTRAP_ROOT != *'"'* ]] || die 'Invalid Go bootstrap path'
        [[ -x $GOLANG_BOOTSTRAP_ROOT/bin/go && -d $GOLANG_BOOTSTRAP_ROOT/src ]] || die 'External Go bootstrap is incomplete'
        "$GOLANG_BOOTSTRAP_ROOT/bin/go" version
    elif [[ $(uname -m) == aarch64 ]]; then
        die 'ARM64 builds require GOLANG_BOOTSTRAP_ROOT pointing to a compatible native Go installation.'
    fi
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
    python3 "$ROOT/scripts/customize.py" apply "$OPENWRT" 2>&1 | tee "$LOGS/customizations.log"
    python3 "$ROOT/scripts/distfeeds.py" install "$CACHE/distfeeds" "$OPENWRT" 2>&1 | tee "$LOGS/distfeeds.log"
    cp "$profile" .config
    if grep -q '@BUILDER_RELEASES_URL@' .config; then
        local release_url
        release_url=$(python3 "$ROOT/scripts/repositories.py" builder)
        sed -i "s|@BUILDER_RELEASES_URL@|$release_url/releases|g" .config
    fi
    printf 'CONFIG_CCACHE_DIR="%s"\n' "$CCACHE_DIR" >> .config
    if [[ -n ${GOLANG_BOOTSTRAP_ROOT:-} ]]; then
        printf 'CONFIG_GOLANG_EXTERNAL_BOOTSTRAP_ROOT="%s"\n# CONFIG_GOLANG_BUILD_BOOTSTRAP is not set\n' \
            "$GOLANG_BOOTSTRAP_ROOT" >> .config
    fi
    # Validate Kconfig against the effective request, including builder overrides.
    cp .config "$WORK/requested.config"
    make defconfig 2>&1 | tee "$LOGS/defconfig.log"
    python3 "$ROOT/scripts/build-meta.py" check-config "$OPENWRT" "$WORK/requested.config"
    python3 "$ROOT/scripts/build-meta.py" keys "$OPENWRT" | tee "$WORK/keys.env"
}

run_make() {
    local name=$1
    shift
    local start=$SECONDS status=0
    {
        echo "phase=$name jobs=$JOBS download_jobs=$DOWNLOAD_JOBS date=$(date -u +%FT%TZ)"
        uname -a
        lscpu || true
        free -h || true
        df -h "$ROOT"
        echo "environment=${BUILD_ENVIRONMENT:-local}"
    } >> "$LOGS/environment.log"
    (command -v vmstat >/dev/null && exec vmstat 30) >> "$LOGS/resources.log" &
    local monitor=$!
    make -C "$OPENWRT" -j"$JOBS" "$@" 2>&1 | tee "$LOGS/$name.log" || status=$?
    kill "$monitor" 2>/dev/null || true
    wait "$monitor" 2>/dev/null || true
    printf '%s\t%s\t%s\n' "$name" "$((SECONDS-start))" "$status" >> "$LOGS/timings.tsv"
    return "$status"
}

restore_build() {
    local kind key
    rm -f "$WORK/cache-restored"
    rm -f "$WORK/restored-downloads-toolchain.json" "$WORK/restored-downloads-build.json"
    [[ ${CLEAN_BUILD:-false} != true ]] || return 0
    for kind in toolchain build; do
        key=$(sed -n "s/^${kind}=//p" "$WORK/keys.env")
        [[ $key =~ ^[a-f0-9]{64}$ ]] || die 'Run configure before restoring build state'
        python3 "$ROOT/scripts/build-cache.py" restore "$kind" "$OPENWRT" "$CACHE/$kind" "$key"
        if [[ $kind == toolchain && ! -f $WORK/cache-restored ]]; then
            if [[ ${GITHUB_ACTIONS:-false} == true ]]; then
                python3 "$ROOT/scripts/cache-seed.py" restore toolchain "$key" "$CACHE/toolchain"
                python3 "$ROOT/scripts/build-cache.py" restore toolchain "$OPENWRT" "$CACHE/toolchain" "$key"
            fi
            # Target state depends on a complete compatible compiler installation.
            [[ -f $WORK/cache-restored ]] || break
        fi
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
    python3 "$ROOT/scripts/build-cache.py" downloads "$OPENWRT"
}

toolchain() {
    if [[ -f $WORK/cache-restored ]]; then
        echo "Checking dependencies of restored $(cat "$WORK/cache-restored") products."
    fi
    run_make tools tools/install
    run_make toolchain toolchain/install
    # Upgrade snapshots without download metadata once; compatible immutable
    # snapshots need no repeated compression or upload on subsequent runs.
    if [[ ! -f $WORK/cache-restored || ! -f $CACHE/toolchain/state.json ]] ||
       ! python3 -c 'import json,sys; sys.exit("downloads" not in json.load(open(sys.argv[1])))' "$CACHE/toolchain/state.json"; then
        save_build toolchain
    fi
}

compile() {
    local status=0
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
    run_make build || status=$?
    if ! "$OPENWRT/staging_dir/host/bin/ccache" -s 2>&1 | tee "$LOGS/ccache.log"; then
        echo 'WARNING: Could not collect ccache statistics.' >&2
    fi
    if (( status != 0 )); then
        echo 'Firmware compilation failed. See build.log and the per-package logs in the diagnostic artifact.' >&2
        echo 'The complete build will not be repeated serially; compiler and download caches are retained.' >&2
    fi
    return "$status"
}

collect() {
    local target="$OPENWRT/bin/targets/airoha/an7581"
    shopt -s nullglob
    images=("$target"/*gemtek_w1700k-ubi*sysupgrade.itb)
    (( ${#images[@]} == 1 )) || die 'Expected exactly one W1700K sysupgrade image'
    python3 "$ROOT/scripts/build-meta.py" check-installed "$OPENWRT"
    python3 "$ROOT/scripts/customize.py" verify "$OPENWRT"
    python3 "$ROOT/scripts/distfeeds.py" verify "$OPENWRT"
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
    cp "$WORK/distfeeds.json" "$dest/distfeeds-source.json"
    cp "$OPENWRT/files/etc/apk/repositories.d/distfeeds.list" "$dest/distfeeds.list"
    cp "$OPENWRT/files/etc/vermagic.txt" "$dest/vermagic.txt"
    cp "$WORK/image-metadata.json" "$dest/image-metadata.json"
    cp "$OPENWRT/public-key.pem" "$dest/public-key.pem"
    "$OPENWRT/scripts/diffconfig.sh" > "$dest/config.diff"
    python3 "$ROOT/scripts/official_npu.py" collect "$OPENWRT" "$dest"
    python3 "$ROOT/scripts/build-meta.py" manifest "$OPENWRT" "$dest"
    # Packages selected with =y are already installed in the image rootfs.
    # Keep diagnostics in the Actions artifact; releases publish only the ITB.
    # SHA256SUMS itself is explicitly excluded from the input file list.
    # shellcheck disable=SC2094
    (cd "$dest" && find . -type f ! -name SHA256SUMS -print0 | sort -z | xargs -0 sha256sum > SHA256SUMS)
    printf '%s\n' "$dest" > "$WORK/artifact-path"
}

case ${1:-all} in
    prepare) prepare ;;
    distfeeds) distfeeds ;;
    configure) configure ;;
    restore) restore_build ;;
    snapshot) save_build build ;;
    download) download ;;
    toolchain) toolchain ;;
    compile) compile ;;
    collect) cd "$OPENWRT"; collect ;;
    all) prepare; distfeeds; configure; restore_build; download; toolchain; compile; cd "$OPENWRT"; collect; save_build build ;;
    *) die 'Usage: bash scripts/build.sh [all|prepare|distfeeds|configure|restore|download|toolchain|compile|collect|snapshot]' ;;
esac
