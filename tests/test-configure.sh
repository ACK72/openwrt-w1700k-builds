#!/usr/bin/env bash
# Exercise configuration inputs and failure diagnostics without downloading feeds.
set -Eeuo pipefail
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
test_root=$(mktemp -d)
trap 'rm -rf -- "$test_root"' EXIT
mkdir -p "$test_root/scripts" "$test_root/fake-bin" "$test_root/configs" \
    "$test_root/.work/openwrt/scripts"
cp "$ROOT/scripts/build.sh" "$ROOT/scripts/build-meta.py" "$test_root/scripts/"
cp "$ROOT/configs/w1700k.config" "$test_root/configs/profile.config"
echo 'CONFIG_PACKAGE_kmod-mt7996e=y' >> "$test_root/configs/profile.config"
echo 'src-git packages https://example.invalid/packages.git^0123456789012345678901234567890123456789' \
    > "$test_root/configs/feeds.lock"
cp "$test_root/configs/feeds.lock" "$test_root/.work/openwrt/feeds.conf.default"
cat > "$test_root/fake-bin/uname" <<'SH'
#!/usr/bin/env bash
echo Linux
SH
cat > "$test_root/.work/openwrt/scripts/feeds" <<'SH'
#!/usr/bin/env bash
set -eu
if [[ $1 == list ]]; then
    cat feeds.conf
elif [[ $1 == install && ${TEST_FAIL_INSTALL:-false} == true ]]; then
    exit 42
fi
SH
cat > "$test_root/fake-bin/make" <<'SH'
#!/usr/bin/env bash
set -eu
[[ $* == defconfig ]]
if [[ ${TEST_DROP_PACKAGE:-false} == true ]]; then
    sed -i '/^CONFIG_PACKAGE_luci-app-wifi7=/d' .config
fi
SH
cat > "$test_root/fake-bin/python3" <<'SH'
#!/usr/bin/env bash
set -eu
if [[ $2 == keys ]]; then
    echo 'toolchain=test-key'
else
    exec "$REAL_PYTHON3" "$@"
fi
SH
chmod +x "$test_root/fake-bin/"* "$test_root/.work/openwrt/scripts/feeds"
export REAL_PYTHON3=${PYTHON3:-$(command -v python3)}
export PATH="$test_root/fake-bin:$PATH" JOBS=2
cd "$test_root"
export CONFIG_FILE=configs/profile.config FEEDS_LOCK=configs/feeds.lock
if ! bash scripts/build.sh configure > configure.log 2>&1; then
    cat configure.log
    exit 1
fi
cmp configs/feeds.lock .work/feeds.lock
echo 'PASS: relative profile and feed lock paths'

# Reusing an exported config must honor the builder-owned cache location.
export CONFIG_FILE="$test_root/configs/profile.config" FEEDS_LOCK="$test_root/configs/feeds.lock"
echo 'CONFIG_CCACHE_DIR="/previous/workspace/cache"' >> "$CONFIG_FILE"
if ! bash scripts/build.sh configure > configure.log 2>&1; then
    cat configure.log
    exit 1
fi
grep -Fq "CONFIG_CCACHE_DIR=\"$test_root/.cache/ccache\"" .work/openwrt/.config
echo 'PASS: relocated cache directory in an exported profile'

# The effective profile must still detect a package silently dropped by Kconfig.
export TEST_DROP_PACKAGE=true
rm .work/feeds.lock
if bash scripts/build.sh configure > configure.log 2>&1; then
    echo 'Dropped package was not rejected' >&2
    exit 1
fi
grep -q 'CONFIG_PACKAGE_luci-app-wifi7: requested y, got n' configure.log
cmp configs/feeds.lock .work/feeds.lock
grep -q '^CONFIG_PACKAGE_luci-app-wifi7=y$' .work/requested.config
echo 'PASS: dropped packages fail with reproducible feed/profile diagnostics'

export TEST_DROP_PACKAGE=false TEST_FAIL_INSTALL=true
rm .work/feeds.lock
if bash scripts/build.sh configure > configure.log 2>&1; then
    echo 'Feed installation failure was hidden' >&2
    exit 1
fi
cmp configs/feeds.lock .work/feeds.lock
echo 'PASS: feed install failure retains its source revisions'
