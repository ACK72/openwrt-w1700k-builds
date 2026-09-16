#!/usr/bin/env bash
# Verify skip decisions against available, deleted and expired artifacts.
set -Eeuo pipefail
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
test_root=$(mktemp -d)
trap 'rm -rf -- "$test_root"' EXIT
mkdir -p "$test_root/scripts" "$test_root/.cache/success" "$test_root/fake-bin"
cp "$ROOT/scripts/should-build.sh" "$test_root/scripts/"
cat > "$test_root/fake-bin/gh" <<'SH'
#!/usr/bin/env bash
echo called >> "$TEST_CALLS"
case $TEST_ARTIFACT in
    available) echo true ;;
    expired) echo false ;;
    deleted) exit 1 ;;
esac
SH
chmod +x "$test_root/fake-bin/gh"
export PATH="$test_root/fake-bin:$PATH" GH_REPO=example/builder
export FINGERPRINT=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
export TEST_CALLS="$test_root/calls" TEST_ARTIFACT=available FORCE=false PUBLISH=false
decision() { bash "$test_root/scripts/should-build.sh"; }
[[ $(decision) == build=true ]]
printf '%s\n' "$FINGERPRINT" > "$test_root/.cache/success/fingerprint"
echo 123 > "$test_root/.cache/success/artifact-id"
[[ $(decision) == build=false ]]
export TEST_ARTIFACT=expired
[[ $(decision) == build=true ]]
export TEST_ARTIFACT=deleted
[[ $(decision) == build=true ]]
export TEST_ARTIFACT=available FORCE=true
[[ $(decision) == build=true ]]
export FORCE=false PUBLISH=true
[[ $(decision) == build=true ]]
export PUBLISH=false
echo mismatched-source > "$test_root/.cache/success/fingerprint"
[[ $(decision) == build=true ]]
printf '%s\n' "$FINGERPRINT" > "$test_root/.cache/success/fingerprint"
echo invalid-id > "$test_root/.cache/success/artifact-id"
[[ $(decision) == build=true ]]
[[ $(wc -l < "$TEST_CALLS") == 3 ]]
echo 'PASS: build decisions (missing, valid, expired, deleted, forced, publish, stale, invalid)'
