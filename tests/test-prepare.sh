#!/usr/bin/env bash
# Exercise real git history and repeatable patch application in disposable repos.
set -Eeuo pipefail
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
test_root=$(mktemp -d)
trap 'rm -rf -- "$test_root"' EXIT
mkdir -p "$test_root/scripts" "$test_root/patches/npu" "$test_root/fake-bin"
cp "$ROOT/scripts/build.sh" "$ROOT/scripts/build-meta.py" "$test_root/scripts/"
cat > "$test_root/fake-bin/uname" <<'SH'
#!/usr/bin/env bash
echo Linux
SH
for tool in clang-18 ld.lld-18 llvm-objcopy-18 llvm-readobj-18 llvm-ar-18; do
    printf '#!/usr/bin/env bash\necho llvm-test\n' > "$test_root/fake-bin/$tool"
done
chmod +x "$test_root/fake-bin/"*
export PATH="$test_root/fake-bin:$PATH" JOBS=2
export GIT_AUTHOR_NAME=Test GIT_AUTHOR_EMAIL=test@example.invalid
export GIT_COMMITTER_NAME=Test GIT_COMMITTER_EMAIL=test@example.invalid
export OPENWRT_REPO="$test_root/upstream-openwrt" OPENWRT_REF=main
export NPU_REPO="$test_root/upstream-npu" NPU_REF=main
for repo in "$OPENWRT_REPO" "$NPU_REPO"; do
    git init -q -b main "$repo"
    git -C "$repo" config core.autocrlf false
    for value in 1 2 3; do
        echo "$value" > "$repo/input"
        git -C "$repo" add input
        git -C "$repo" commit -qm "revision $value"
    done
done
cat > "$test_root/patches/npu/0001-fixture.patch" <<'PATCH'
--- a/input
+++ b/input
@@ -1 +1 @@
-3
+patched
PATCH
prepare() {
    if ! bash "$test_root/scripts/build.sh" prepare > "$test_root/prepare.log" 2>&1; then
        cat "$test_root/prepare.log"
        exit 1
    fi
}
prepare
[[ $(git -C "$test_root/.work/openwrt" rev-list --count HEAD) == 3 ]]
[[ $(git -C "$test_root/.work/openwrt" rev-parse --is-shallow-repository) == false ]]
[[ $(git -C "$test_root/.work/openwrt" rev-parse '@{u}') == "$(git -C "$OPENWRT_REPO" rev-parse HEAD)" ]]
[[ $(cat "$test_root/.work/npu/input") == patched ]]
# Git Bash may emulate ln -s by copying the empty directory. Linux keeps the
# real symlink, while the Windows smoke test recreates only this empty fixture.
if [[ ! -L $test_root/.work/openwrt/dl ]]; then
    rmdir "$test_root/.work/openwrt/dl"
fi
prepare
[[ $(cat "$test_root/.work/npu/input") == patched ]]
[[ $(cat "$NPU_REPO/input") == 3 ]]
echo 'PASS: full OpenWrt history, upstream tracking and repeatable NPU patches'

# Fake only the compiler/integration calls; cache validation uses real hashes.
cat > "$test_root/fake-bin/python3" <<'SH'
#!/usr/bin/env bash
set -eu
if [[ $1 == */airoha-npu-fdk-build ]]; then
    echo build >> "$TEST_NPU_CALLS"
    while (( $# )); do
        case $1 in
            -o) output=$2; shift ;;
            --debug-directory) debug=$2; shift ;;
        esac
        shift
    done
    mkdir -p "$debug"
    echo rv32 > "${output}_rv32.bin"
    echo data > "${output}_data.bin"
    echo elf > "$debug/firmware.elf"
    echo map > "$debug/firmware.map"
fi
SH
chmod +x "$test_root/fake-bin/python3"
export TEST_NPU_CALLS="$test_root/npu-calls"
npu() {
    if ! bash "$test_root/scripts/build.sh" npu > "$test_root/npu.log" 2>&1; then
        cat "$test_root/npu.log"
        exit 1
    fi
}
npu
npu
[[ $(wc -l < "$TEST_NPU_CALLS") == 1 ]]
rm "$test_root/.cache/npu/debug/firmware.map"
npu
[[ $(wc -l < "$TEST_NPU_CALLS") == 2 ]]
echo corrupted > "$test_root/.cache/npu/en7581_MT7996_npu_rv32.bin"
npu
[[ $(wc -l < "$TEST_NPU_CALLS") == 3 ]]
echo corrupted > "$test_root/.cache/npu/debug/firmware.elf"
npu
[[ $(wc -l < "$TEST_NPU_CALLS") == 4 ]]
echo 'PASS: NPU cache reuse and rebuilding missing/corrupt outputs'
