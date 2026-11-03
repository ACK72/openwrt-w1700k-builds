#!/usr/bin/env python3
"""Validate the pinned NPU firmware that the fanboy stack installs, and its installed blobs."""
import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path

PACKAGE = "airoha-en7581-mt7996-npu-firmware"
BINARIES = ("en7581_MT7996_npu_rv32.bin", "en7581_MT7996_npu_data.bin")
RECIPES = ("package/firmware/linux-firmware/Makefile",
           "package/firmware/linux-firmware/airoha.mk")
FILES = "package/firmware/linux-firmware/files/airoha"
# fanboy's "linux-firmware: use NPU v0.8 firmware" copies the v0.8 test binaries
# unchanged from this commit. The source publishes no license for them.
PROVIDER = {"provider": "airoha-npu", "version": "0.8-test",
            "source": "https://github.com/zhengping-zhang/airoha-npu",
            "commit": "1df6a36f849ea52cadfc326ec5b583d658be630e"}
SHA256 = {
    "en7581_MT7996_npu_rv32.bin": "7068a987bb95e89129a69de10d598f234a4400023eb23aacc8eb377e5f0fe0ea",
    "en7581_MT7996_npu_data.bin": "6fd9506e399ebb309801ac2ecc74d3e10fa66731afc828c76fde8a67b2153f49",
}


def npu_info(openwrt):
    # CI provides the exact official ancestor; local checkouts use their HEAD.
    stack = openwrt.parent / "source-stack.json"
    upstream = json.loads(stack.read_text())["upstream"] if stack.exists() else "HEAD"
    if upstream != "HEAD" and not re.fullmatch(r"[a-f0-9]{40}", upstream):
        raise ValueError("Invalid official source revision")
    official = {name: subprocess.check_output([
        "git", "-c", f"safe.directory={openwrt.resolve()}", "-C", str(openwrt),
        "show", f"{upstream}:{name}"]) for name in RECIPES}
    # The recipe may differ from the official one only by installing the pinned blobs.
    # Local checkouts compare with their own HEAD, which already installs them.
    expected = official[RECIPES[1]]
    pinned = {name: f"./files/airoha/{name}".encode() for name in BINARIES}
    if upstream != "HEAD":
        for name in BINARIES:
            stock = f"$(PKG_BUILD_DIR)/airoha/{name}".encode()
            if expected.count(stock) != 1:
                raise ValueError("Unexpected upstream linux-firmware recipe; review the NPU provider")
            expected = expected.replace(stock, pinned[name])
    if (any(expected.count(line) != 1 for line in pinned.values())
            or f"BuildPackage,{PACKAGE}".encode() not in expected):
        raise ValueError("Unexpected linux-firmware recipe; review the NPU provider")
    hashes = {}
    for name, content in ((RECIPES[0], official[RECIPES[0]]), (RECIPES[1], expected)):
        if (openwrt / name).read_bytes() != content:
            raise ValueError(f"NPU recipe was modified: {name}")
        hashes[name] = hashlib.sha256(content).hexdigest()
    files = openwrt / FILES
    present = sorted(p.name for p in files.iterdir()) if files.is_dir() else []
    if present != sorted(BINARIES):
        raise ValueError(f"Unexpected NPU firmware files: {', '.join(present) or 'none'}")
    for name in BINARIES:
        if hashlib.sha256((files / name).read_bytes()).hexdigest() != SHA256[name]:
            raise ValueError(f"NPU firmware differs from the pinned v0.8 test binary: {name}")
    if (openwrt / "package/firmware/airoha-npu-fdk").exists():
        raise ValueError("FDK replacement package remains; use a fresh managed OpenWrt checkout")
    return {**PROVIDER, "sha256": SHA256, "recipes_sha256": hashes}


def npu_identity(info):
    """Keep target/package caches separate from FDK and other blob revisions."""
    return hashlib.sha256(json.dumps(info, sort_keys=True).encode()).hexdigest()


def collect_npu(openwrt, output):
    info = npu_info(openwrt)
    roots = list((openwrt / "build_dir").glob("target-*/root-airoha"))
    if len(roots) != 1:
        raise ValueError("Expected exactly one image rootfs")
    destination = output / "npu"
    destination.mkdir(parents=True, exist_ok=True)
    for name in BINARIES:
        content = (openwrt / FILES / name).read_bytes()
        if (roots[0] / "lib/firmware/airoha" / name).read_bytes() != content:
            raise ValueError(f"Image contains a different NPU blob: {name}")
        (destination / name).write_bytes(content)
    (destination / "SOURCE").write_text(
        f"{info['source']} {info['commit']}\nNo license is published with these binaries.\n")
    print("Verified both installed NPU blobs byte-for-byte against the pinned v0.8 test binaries")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("check").add_argument("openwrt", type=Path)
    collect = sub.add_parser("collect")
    collect.add_argument("openwrt", type=Path)
    collect.add_argument("output", type=Path)
    args = parser.parse_args()
    if args.command == "check":
        print(json.dumps(npu_info(args.openwrt), sort_keys=True))
    else:
        collect_npu(args.openwrt, args.output)


if __name__ == "__main__":
    main()
