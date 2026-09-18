#!/usr/bin/env python3
"""Pin and cache the official snapshot's APK feeds without importing its kernel."""
import argparse
import hashlib
import json
import re
import struct
import subprocess
import tempfile
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

BASE = "https://downloads.openwrt.org/snapshots/targets/airoha/an7581/"
IMAGE = "openwrt-airoha-an7581-airoha_an7581-evb-squashfs-sysupgrade.bin"
FEEDS = "etc/apk/repositories.d/distfeeds.list"
VERMAGIC = "etc/vermagic.txt"
FILES = {"distfeeds.list": FEEDS, "vermagic.txt": VERMAGIC}
KMOD = re.compile(re.escape(BASE) + r"kmods/([0-9][0-9A-Za-z._-]*-[0-9]+-([a-f0-9]{32}))/packages[.]adb")


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def fetch(url, limit, method="GET"):
    for attempt in range(3):
        try:
            with urlopen(Request(url, method=method, headers={"User-Agent": "w1700k-builder"}), timeout=30) as response:
                data = response.read(limit + 1) if method == "GET" else b""
            if len(data) > limit:
                raise ValueError(f"Download exceeds size limit: {url}")
            return data
        except (URLError, TimeoutError):
            if attempt == 2:
                raise
            time.sleep(2 ** attempt)


def resolve(path):
    # profiles.json is ~12 KB; sha256sums also lists historical kmods and is MBs.
    profiles = json.loads(fetch(BASE + "profiles.json", 1024 * 1024))
    if profiles.get("target") != "airoha/an7581":
        raise ValueError("Unexpected official image target")
    images = profiles.get("profiles", {}).get("airoha_an7581-evb", {}).get("images", [])
    matches = [item for item in images if item.get("name") == IMAGE
               and item.get("type") == "sysupgrade" and item.get("filesystem") == "squashfs"]
    if len(matches) != 1 or not re.fullmatch(r"[a-f0-9]{64}", matches[0].get("sha256", "")):
        raise ValueError("Official image checksum is missing or ambiguous in profiles.json")
    source = {"url": BASE + IMAGE, "sha256": matches[0]["sha256"]}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(source, indent=2) + "\n", encoding="utf-8")
    # The cache is independent of runner architecture and invalidated by extractor changes.
    extractor = sha256(Path(__file__).read_bytes())[:16]
    print(f"cache-key=w1700k-v2-shared-distfeeds-{extractor}-{source['sha256']}")


def parse_feeds(data):
    if not data or len(data) > 64 * 1024:
        raise ValueError("Empty or oversized distfeeds.list")
    urls = [line.strip() for line in data.decode("utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")]
    for url in urls:
        if not re.fullmatch(r"https://downloads[.]openwrt[.]org/snapshots/[A-Za-z0-9_./-]+/packages[.]adb", url):
            raise ValueError(f"Unexpected official feed URL: {url}")
    if BASE + "packages/packages.adb" not in urls:
        raise ValueError("Missing airoha/an7581 core feed")
    kmods = [KMOD.fullmatch(url) for url in urls if "/kmods/" in url]
    if len(kmods) != 1 or kmods[0] is None:
        raise ValueError("Expected exactly one airoha/an7581 kmods feed")
    return {"kernel": kmods[0][1], "vermagic": kmods[0][2], "kmods_url": kmods[0][0]}


def squashfs_offset(data):
    candidates = []
    for match in re.finditer(b"hsqs", data):
        offset = match.start()
        if offset + 96 > len(data):
            continue
        major, minor = struct.unpack_from("<HH", data, offset + 28)
        size = struct.unpack_from("<Q", data, offset + 40)[0]
        if (major, minor) == (4, 0) and 96 <= size <= len(data) - offset:
            candidates.append(offset)
    if len(candidates) != 1:
        raise ValueError("Expected exactly one SquashFS filesystem in the official image")
    return candidates[0]


def extract(image, offset):
    # Read only the feed list; never unpack/install the official kernel or rootfs.
    return subprocess.check_output(
        ["unsquashfs", "-cat", "-o", str(offset), str(image), FEEDS], timeout=60)


def read_cache(cache, source=None):
    metadata = json.loads((cache / "source.json").read_text(encoding="utf-8"))
    if source is not None and metadata["source"] != source:
        raise ValueError("Cached official image does not match the selected snapshot")
    contents = {name: (cache / name).read_bytes() for name in FILES}
    if metadata["files"] != {name: sha256(data) for name, data in contents.items()}:
        raise ValueError("Cached distfeeds checksum mismatch")
    feeds = parse_feeds(contents["distfeeds.list"])
    if contents["vermagic.txt"] != (feeds["vermagic"] + "\n").encode():
        raise ValueError("distfeeds.list and vermagic.txt do not describe the same kernel")
    return contents, metadata


def prepare(source_path, cache):
    source = json.loads(source_path.read_text(encoding="utf-8"))
    if source.get("url") != BASE + IMAGE or not re.fullmatch(r"[a-f0-9]{64}", source.get("sha256", "")):
        raise ValueError("Invalid official image identity")
    try:
        contents, _ = read_cache(cache, source)
    except (OSError, ValueError, KeyError):
        print("Downloading the selected official image to refresh distfeeds")
        image = fetch(source["url"], 128 * 1024 * 1024)
        if sha256(image) != source["sha256"]:
            raise ValueError("Official image checksum changed; resolve the snapshot again before retrying")
        offset = squashfs_offset(image)
        with tempfile.TemporaryDirectory(prefix="w1700k-distfeeds-") as temp:
            path = Path(temp) / IMAGE
            path.write_bytes(image)
            distfeeds = extract(path, offset)
        feeds = parse_feeds(distfeeds)
        contents = {"distfeeds.list": distfeeds, "vermagic.txt": (feeds["vermagic"] + "\n").encode()}
        metadata = {"source": source, "files": {name: sha256(data) for name, data in contents.items()}}
        # Validate repository availability before committing the cache's metadata.
        fetch(feeds["kmods_url"], 0, "HEAD")
        cache.mkdir(parents=True, exist_ok=True)
        for name, data in contents.items():
            (cache / name).write_bytes(data)
        (cache / "source.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    else:
        fetch(parse_feeds(contents["distfeeds.list"])["kmods_url"], 0, "HEAD")
        print("Using verified cached distfeeds; image download and extraction skipped")


def install(cache, openwrt):
    source_path = openwrt.parent / "distfeeds-source.json"
    source = json.loads(source_path.read_text(encoding="utf-8"))
    contents, metadata = read_cache(cache, source)
    hook = "cp ../../../files/etc/vermagic.txt $(LINUX_DIR)/.vermagic"
    if hook not in (openwrt / "include/kernel-defaults.mk").read_text(encoding="utf-8"):
        raise ValueError("OpenWrt source no longer supports the selected vermagic override")
    for name, relative in FILES.items():
        path = openwrt / "files" / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(contents[name])
        path.chmod(0o644)
    (openwrt.parent / "distfeeds.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    print("Installed official distfeeds and vermagic for the locally compiled kernel")


def verify(openwrt):
    metadata = json.loads((openwrt.parent / "distfeeds.json").read_text(encoding="utf-8"))
    roots = list((openwrt / "build_dir").glob("target-*/root-airoha"))
    kernels = list((openwrt / "build_dir").glob("target-*/linux-*/linux-*/.vermagic"))
    if len(roots) != 1 or len(kernels) != 1:
        raise ValueError("Expected one compiled rootfs and kernel vermagic")
    for name, relative in FILES.items():
        expected = metadata["files"][name]
        if sha256((openwrt / "files" / relative).read_bytes()) != expected:
            raise ValueError(f"Build input changed after distfeeds selection: {name}")
        if sha256((roots[0] / relative).read_bytes()) != expected:
            raise ValueError(f"Official {name} missing or changed in compiled rootfs")
    if kernels[0].read_text().strip() != (openwrt / "files" / VERMAGIC).read_text().strip():
        raise ValueError("Locally compiled kernel did not use the selected vermagic")
    print("Verified official feeds and selected vermagic in the locally built firmware")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("resolve").add_argument("source", type=Path)
    prepare_parser = sub.add_parser("prepare")
    prepare_parser.add_argument("source", type=Path)
    prepare_parser.add_argument("cache", type=Path)
    install_parser = sub.add_parser("install")
    install_parser.add_argument("cache", type=Path)
    install_parser.add_argument("openwrt", type=Path)
    sub.add_parser("verify").add_argument("openwrt", type=Path)
    args = parser.parse_args()
    if args.command == "resolve":
        resolve(args.source)
    elif args.command == "prepare":
        prepare(args.source, args.cache)
    elif args.command == "install":
        install(args.cache, args.openwrt)
    else:
        verify(args.openwrt)


if __name__ == "__main__":
    main()
