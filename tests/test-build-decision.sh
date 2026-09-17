#!/usr/bin/env bash
# Verify forced builds and the fail-open API behavior; release policy has Python tests.
set -Eeuo pipefail
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
test_root=$(mktemp -d)
trap 'rm -rf -- "$test_root"' EXIT
mkdir -p "$test_root/scripts" "$test_root/fake-bin"
cp "$ROOT/scripts/should-build.sh" "$test_root/scripts/"
cat > "$test_root/fake-bin/python3" <<'SH'
#!/usr/bin/env bash
echo called >> "$TEST_CALLS"
case $TEST_RELEASE in
    available) echo build=false ;;
    missing) echo build=true ;;
    api-failure) exit 1 ;;
esac
SH
chmod +x "$test_root/fake-bin/python3"
export PATH="$test_root/fake-bin:$PATH"
export FINGERPRINT=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
export TEST_CALLS="$test_root/calls" TEST_RELEASE=available FORCE=false
decision() { bash "$test_root/scripts/should-build.sh"; }
[[ $(decision) == build=false ]]
export TEST_RELEASE=missing
[[ $(decision) == build=true ]]
export TEST_RELEASE=api-failure
[[ $(decision) == build=true ]]
export TEST_RELEASE=available FORCE=true
[[ $(decision) == build=true ]]
[[ $(wc -l < "$TEST_CALLS") == 3 ]]
export FINGERPRINT=invalid
if decision >/dev/null 2>&1; then exit 1; fi
echo 'PASS: published-release skip, missing release, API failure and force'
