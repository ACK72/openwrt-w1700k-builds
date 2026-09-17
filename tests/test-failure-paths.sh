#!/usr/bin/env bash
# Exercise make/tee exit status and the diagnostic retry without compiling.
set -Eeuo pipefail
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
test_root=$(mktemp -d)
trap 'rm -rf -- "$test_root"' EXIT
mkdir -p "$test_root/scripts" "$test_root/fake-bin" "$test_root/.work/openwrt/staging_dir/host/bin"
cp "$ROOT/scripts/build.sh" "$test_root/scripts/build.sh"
cat > "$test_root/fake-bin/uname" <<'SH'
#!/usr/bin/env bash
echo Linux
SH
cat > "$test_root/fake-bin/make" <<'SH'
#!/usr/bin/env bash
echo "$*" >> "$TEST_CALLS"
case $TEST_MODE in
    success) exit 0 ;;
    fail) exit 42 ;;
    retry) [[ $(wc -l < "$TEST_CALLS") -ge 2 ]] ;;
esac
SH
cat > "$test_root/.work/openwrt/staging_dir/host/bin/ccache" <<'SH'
#!/usr/bin/env bash
[[ ${1:-} != -z ]] || exit 0
echo stats >> "$TEST_STATS"
exit "${TEST_STATS_EXIT:-0}"
SH
chmod +x "$test_root/fake-bin/"* "$test_root/.work/openwrt/staging_dir/host/bin/ccache"
export PATH="$test_root/fake-bin:$PATH" JOBS=2
export TEST_CALLS="$test_root/calls" TEST_STATS="$test_root/stats"
for mode in success retry fail; do
    export TEST_MODE=$mode
    : > "$TEST_CALLS"
    : > "$TEST_STATS"
    if bash "$test_root/scripts/build.sh" compile > "$test_root/output" 2>&1; then
        [[ $mode != fail ]] || { cat "$test_root/output"; exit 1; }
        [[ $(wc -l < "$TEST_STATS") == 1 ]]
    else
        [[ $mode == fail ]] || { cat "$test_root/output"; exit 1; }
        [[ ! -s $TEST_STATS ]]
    fi
    if [[ $mode == success ]]; then
        [[ $(wc -l < "$TEST_CALLS") == 1 ]]
    else
        [[ $(wc -l < "$TEST_CALLS") == 2 ]]
        tail -n1 "$TEST_CALLS" | grep -q -- '-j1 V=s'
    fi
    echo "PASS: compilation $mode"
done
export TEST_MODE=fail
if bash "$test_root/scripts/build.sh" download > "$test_root/output" 2>&1; then
    echo 'Download failure was hidden by tee' >&2
    exit 1
fi
echo 'PASS: download failure propagates'

export TEST_MODE=success TEST_STATS_EXIT=42
if ! bash "$test_root/scripts/build.sh" compile > "$test_root/output" 2>&1; then
    cat "$test_root/output"
    echo 'Statistics failure discarded a successful compilation' >&2
    exit 1
fi
grep -q 'WARNING: Could not collect ccache statistics' "$test_root/output"
echo 'PASS: statistics failure does not discard compiled firmware'
