#!/usr/bin/env python3
"""Content-based cache keys, strict firmware integration, and build provenance."""
import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLCHAIN_INPUTS = (
    "tools", "toolchain", "include", "config", "target/Config.in", "target/Makefile",
    "target/linux/Makefile", "target/linux/airoha", "target/linux/generic", "scripts",
    "Makefile", "rules.mk", "Config.in", ".config",
)
PACKAGE = "airoha-en7581-mt7996-npu-firmware"
BINARIES = ("en7581_MT7996_npu_rv32.bin", "en7581_MT7996_npu_data.bin")
REQUIRED_CONFIG = (
    "CONFIG_TARGET_airoha_an7581_DEVICE_gemtek_w1700k-ubi",
    "CONFIG_PACKAGE_airoha-en7581-mt7996-npu-firmware",
    "CONFIG_PACKAGE_kmod-mt7996e", "CONFIG_CCACHE",
)


def git(path, *args):
    return subprocess.check_output(["git", "-C", str(path), *args], text=True).strip()


def digest_paths(root, names):
    digest = hashlib.sha256()
    for name in sorted(names):
        base = root / name
        paths = sorted(base.rglob("*")) if base.is_dir() and not base.is_symlink() else [base]
        for path in paths:
            if (path.is_dir() and not path.is_symlink()) or "__pycache__" in path.parts:
                continue
            digest.update(path.relative_to(root).as_posix().encode() + b"\0")
            digest.update((path.lstat().st_mode & 0o777).to_bytes(2, "big"))
            if path.is_symlink():
                digest.update(b"link\0" + os.readlink(path).encode())
            else:
                digest.update(b"file\0" + path.read_bytes())
            digest.update(b"\0")
    return digest.hexdigest()


def read_config(path):
    values = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        disabled = re.fullmatch(r"# (CONFIG_\S+) is not set", line)
        if disabled:
            values[disabled[1]] = "n"
        elif line.startswith("CONFIG_") and "=" in line:
            name, value = line.split("=", 1)
            values[name] = value
    return values


def config_digest(path, toolchain=False):
    """Package selection and release labels do not change compiler binaries."""
    values = read_config(path)
    ignored = ("CONFIG_VERSION_", "CONFIG_PACKAGE_") if toolchain else ("CONFIG_VERSION_",)
    # Feeds frequently add unselected packages. An absent boolean and an
    # explicitly disabled boolean are equivalent after make defconfig.
    values = {key: value for key, value in values.items()
              if value != "n" and not key.startswith(ignored)}
    return hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest()


def check_config(openwrt, profile):
    actual = read_config(openwrt / ".config")
    expected = read_config(profile)
    expected.update(dict.fromkeys(REQUIRED_CONFIG, "y"))
    mismatches = [
        f"{name}: requested {value}, got {actual.get(name, 'n')}"
        for name, value in expected.items()
        if actual.get(name, "n") != value
    ]
    if mismatches:
        raise RuntimeError("Configuration lost after defconfig:\n" + "\n".join(mismatches))


def install_npu(openwrt, npu, firmware):
    # Replace just the MT7996 definition, leaving MT7992/AN7583 packages intact.
    # Fail closed if the upstream recipe changes instead of building vendor blobs.
    recipe = openwrt / "package/firmware/linux-firmware/airoha.mk"
    text = recipe.read_text()
    marker = "# MT7996 firmware is provided by package/firmware/airoha-npu-fdk."
    pattern = (
        rf"Package/{PACKAGE} = [^\n]+\n"
        rf"define Package/{PACKAGE}/install\n.*?\nendef\n\n"
        rf"\$\(eval \$\(call BuildPackage,{PACKAGE}\)\)"
    )
    if marker not in text:
        text, count = re.subn(pattern, marker, text, flags=re.S)
        if count != 1:
            raise RuntimeError("MT7996 linux-firmware recipe changed; review integration")
    if f"BuildPackage,{PACKAGE}" in text or f"Package/{PACKAGE}" in text:
        raise RuntimeError("MT7996 linux-firmware recipe changed; duplicate definition")
    for name in BINARIES:
        if not (firmware / name).is_file() or not (firmware / name).stat().st_size:
            raise RuntimeError(f"Missing/empty FDK output: {name}")
    # OpenWrt disables compression by default. Cache capacity is constrained in
    # Actions, so keep ccache's fast zstd compression in this managed checkout.
    rules = openwrt / "rules.mk"
    rules_text = rules.read_text()
    rules_text = rules_text.replace(
        "export CCACHE_NOCOMPRESS:=true", "export CCACHE_COMPRESS:=true"
    )
    package = openwrt / "package/firmware/airoha-npu-fdk"
    (package / "files").mkdir(parents=True, exist_ok=True)
    revision = git(npu, "rev-parse", "HEAD")
    template = (ROOT / "package/airoha-npu-fdk/Makefile").read_text()
    (package / "Makefile").write_text(template.replace("@NPU_VERSION@", "0~" + revision[:12]))
    for name in BINARIES:
        shutil.copy2(firmware / name, package / "files" / name)
    shutil.copy2(npu / "LICENSE", package / "files/LICENSE")
    recipe.write_text(text)
    rules.write_text(rules_text)


def keys(openwrt, npu):
    feeds = {
        p.name: git(p, "rev-parse", "HEAD")
        for p in sorted((openwrt / "feeds").iterdir())
        if p.is_dir() and not p.is_symlink() and (p / ".git").exists()
    }
    # A browser/SDK update in the runner image is unrelated to the compiler.
    # Include the build dependencies and their installed dependency closure.
    host = subprocess.check_output(
        ["bash", str(ROOT / "scripts/host-key.sh")], text=True
    )
    # Use tracked inputs only: generated conf binaries and pycache must not
    # invalidate a toolchain cache after make defconfig.
    tracked = git(openwrt, "ls-files", "--", *TOOLCHAIN_INPUTS).splitlines()
    source_hash = digest_paths(openwrt, tracked)
    builder_hash = digest_paths(ROOT, ["scripts", "configs", "package", "patches", ".github"])
    host_hash = hashlib.sha256((platform.machine() + host).encode()).hexdigest()
    toolchain = hashlib.sha256(
        ("toolchain-v2" + source_hash + host_hash + config_digest(openwrt / ".config", True)).encode()
    ).hexdigest()
    build = hashlib.sha256((toolchain + config_digest(openwrt / ".config")).encode()).hexdigest()
    state = {
        "openwrt": git(openwrt, "rev-parse", "HEAD"),
        "npu": git(npu, "rev-parse", "HEAD"),
        "feeds": feeds, "builder": builder_hash, "toolchain": toolchain,
        "host": host_hash, "build": build,
        "config": digest_paths(openwrt, [".config"]), "channel": "ubi2-oc",
    }
    fingerprint = hashlib.sha256(json.dumps(state, sort_keys=True).encode()).hexdigest()
    state["fingerprint"] = fingerprint
    (openwrt.parent / "build-state.json").write_text(json.dumps(state, indent=2) + "\n")
    print(f"toolchain={toolchain}\nbuild={build}\nfingerprint={fingerprint}")


def manifest(openwrt, npu, output):
    state = json.loads((openwrt.parent / "build-state.json").read_text())
    state["build_type"] = "release"
    try:
        state["builder_commit"] = git(ROOT, "rev-parse", "--verify", "HEAD")
    except subprocess.CalledProcessError:
        state["builder_commit"] = "uncommitted (see builder content hash)"
    state["source_date_epoch"] = git(openwrt, "show", "-s", "--format=%ct", "HEAD")
    state["built_at"] = datetime.now(timezone.utc).isoformat()
    state["changelog"] = git(openwrt, "log", "-20", "--format=%h %s", "--abbrev=10", "HEAD").splitlines()
    state["npu_compiler"] = subprocess.check_output(["clang-18", "--version"], text=True).strip()
    state["npu_patches"] = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted((ROOT / "patches/npu").glob("*.patch"))
    }
    state["firmware_sha256"] = {
        name: hashlib.sha256((output / "npu" / name).read_bytes()).hexdigest()
        for name in BINARIES
    }
    (output / "build-manifest.json").write_text(json.dumps(state, indent=2) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("install-npu", "keys", "manifest", "check-config"):
        subparser = subparsers.add_parser(command)
        subparser.add_argument("openwrt", type=Path)
        if command == "check-config":
            subparser.add_argument("profile", type=Path)
        else:
            subparser.add_argument("npu", type=Path)
            if command != "keys":
                subparser.add_argument("output", type=Path)
    args = parser.parse_args()
    if args.command == "check-config":
        check_config(args.openwrt, args.profile)
    elif args.command == "keys":
        keys(args.openwrt, args.npu)
    elif args.command == "install-npu":
        install_npu(args.openwrt, args.npu, args.output)
    else:
        manifest(args.openwrt, args.npu, args.output)


if __name__ == "__main__":
    main()
