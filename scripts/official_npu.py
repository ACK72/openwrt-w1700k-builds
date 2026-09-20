#!/usr/bin/env python3
"""Validate the unchanged OpenWrt linux-firmware provider and its installed blobs."""
import argparse
import hashlib
import json
import re
import subprocess
import tarfile
from pathlib import Path

PACKAGE = "airoha-en7581-mt7996-npu-firmware"
BINARIES = ("en7581_MT7996_npu_rv32.bin", "en7581_MT7996_npu_data.bin")
RECIPES = ("package/firmware/linux-firmware/Makefile",
           "package/firmware/linux-firmware/airoha.mk")


def stock_npu_info(openwrt):
    # CI provides the exact official ancestor; local checkouts use their HEAD.
    stack = openwrt.parent / "source-stack.json"
    upstream = json.loads(stack.read_text())["upstream"] if stack.exists() else "HEAD"
    if upstream != "HEAD" and not re.fullmatch(r"[a-f0-9]{40}", upstream):
        raise ValueError("Invalid official source revision")
    hashes = {}
    for name in RECIPES:
        content = (openwrt / name).read_bytes()
        original = subprocess.check_output([
            "git", "-c", f"safe.directory={openwrt.resolve()}", "-C", str(openwrt),
            "show", f"{upstream}:{name}"])
        if content != original:
            raise ValueError(f"Official NPU recipe was modified: {name}")
        hashes[name] = hashlib.sha256(content).hexdigest()
    if (openwrt / "package/firmware/airoha-npu-fdk").exists():
        raise ValueError("FDK replacement package remains; use a fresh managed OpenWrt checkout")
    makefile = (openwrt / RECIPES[0]).read_text()
    version = re.search(r"^PKG_VERSION:=(\d+)$", makefile, re.M)
    checksum = re.search(r"^PKG_HASH:=([a-f0-9]{64})$", makefile, re.M)
    if not version or not checksum or f"BuildPackage,{PACKAGE}" not in (openwrt / RECIPES[1]).read_text():
        raise ValueError("Unexpected upstream linux-firmware recipe; review the provider")
    return {"provider": "linux-firmware", "version": version[1],
            "archive_sha256": checksum[1], "recipes_sha256": hashes}


def npu_identity(info):
    """Keep target/package caches separate from FDK and other blob revisions."""
    return hashlib.sha256(json.dumps(info, sort_keys=True).encode()).hexdigest()


def collect_stock_npu(openwrt, output):
    info = stock_npu_info(openwrt)
    archive = openwrt / "dl" / f"linux-firmware-{info['version']}.tar.xz"
    with archive.open("rb") as stream:
        if hashlib.file_digest(stream, "sha256").hexdigest() != info["archive_sha256"]:
            raise ValueError("Original linux-firmware archive checksum mismatch")
    roots = list((openwrt / "build_dir").glob("target-*/root-airoha"))
    if len(roots) != 1:
        raise ValueError("Expected exactly one image rootfs")
    prefix = f"linux-firmware-{info['version']}/"
    wanted = {prefix + "airoha/" + name: name for name in BINARIES}
    wanted[prefix + "LICENSES/LICENSE.airoha"] = "LICENSE"
    content = {}
    # Read the RV32 program and its data from the same verified release archive.
    # Never unpack paths supplied by the archive onto the filesystem.
    with tarfile.open(archive, mode="r|xz") as source:
        for member in source:
            name = wanted.get(member.name)
            if name is None:
                continue
            if name in content or not member.isfile() or not 0 < member.size < 32 * 1024 * 1024:
                raise ValueError("Invalid original firmware archive member")
            content[name] = source.extractfile(member).read()
            if name in BINARIES:
                installed = roots[0] / "lib/firmware/airoha" / name
                if installed.read_bytes() != content[name]:
                    raise ValueError(f"Image contains a replaced NPU blob: {name}")
    if set(content) != set(wanted.values()):
        raise ValueError("Original archive is missing required NPU firmware or license")
    destination = output / "npu"
    destination.mkdir(parents=True, exist_ok=True)
    for name, data in content.items():
        (destination / name).write_bytes(data)
    print("Verified both installed NPU blobs byte-for-byte against the official linux-firmware archive")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("check").add_argument("openwrt", type=Path)
    collect = sub.add_parser("collect")
    collect.add_argument("openwrt", type=Path)
    collect.add_argument("output", type=Path)
    args = parser.parse_args()
    if args.command == "check":
        print(json.dumps(stock_npu_info(args.openwrt), sort_keys=True))
    else:
        collect_stock_npu(args.openwrt, args.output)


if __name__ == "__main__":
    main()
