#!/usr/bin/env python3
"""Keep successful build products and restore mtimes only for identical inputs.

Adapted from BuildWrt's persistent build tree/content-based synchronization idea.
The new checkout, configuration and feeds are never overwritten by an old cache.
"""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

SOURCE_ROOTS = ("tools", "toolchain", "include", "config", "target", "scripts", "package", "feeds", "files")
ROOT_INPUTS = ("Makefile", "rules.mk", "Config.in", ".config", "feeds.conf")
SCHEMA = 3


def signature(path):
    value = os.readlink(path).encode() if path.is_symlink() else path.read_bytes()
    return [hashlib.sha256(value).hexdigest(), path.lstat().st_mode & 0o777, path.is_symlink()]


def input_files(root):
    for name in ROOT_INPUTS:
        path = root / name
        if path.is_file() or path.is_symlink():
            yield path
    for name in SOURCE_ROOTS:
        for parent, dirs, files in os.walk(root / name, followlinks=False):
            dirs[:] = [d for d in dirs if d not in (".git", ".svn", "__pycache__")]
            for item in files:
                path = Path(parent) / item
                if path.is_file() or path.is_symlink():
                    yield path


def source_state(root):
    return {p.relative_to(root).as_posix(): [*signature(p), p.lstat().st_mtime_ns]
            for p in input_files(root)}


def restore_mtimes(root, previous):
    """Never hide changed content, permission changes, or deleted package inputs."""
    restored = 0
    current = {p.relative_to(root).as_posix(): p for p in input_files(root)}
    for name, path in current.items():
        old = previous.get(name)
        if old and signature(path) == old[:3]:
            if path.is_symlink():
                # OpenWrt's timestamp checker ignores symlinks themselves.
                continue
            os.utime(path, ns=(old[3], old[3]))
            restored += 1
    # A removed patch/file must also invalidate the containing package recipe.
    # timestamp.pl cannot see files that no longer exist.
    for name in previous.keys() - current.keys():
        relative = Path(name)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("Invalid source manifest path")
        for parent in (root / relative).parents:
            if parent == root:
                break
            recipe = parent / "Makefile"
            if recipe.is_file():
                recipe.touch()
                break
    return restored


def product_paths(root, kind):
    return sorted(path for name in ("build_dir", "staging_dir") for path in (root / name).glob("*")
                  if (path.name == "host" or path.name.startswith("toolchain-")) == (kind == "toolchain"))


def products(root, kind):
    paths = product_paths(root, kind)
    required = ("host", "toolchain-") if kind == "toolchain" else ("target-",)
    if any(not any(p.parent.name == directory and p.name.startswith(prefix) and p.is_dir()
                   and not p.is_symlink() for p in paths)
           for directory in ("build_dir", "staging_dir") for prefix in required):
        raise RuntimeError("Incomplete build products; refusing to save cache")
    return [p.relative_to(root).as_posix() for p in paths]


def file_digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def download_state(root):
    return {p.name: [file_digest(p), p.stat().st_size, p.stat().st_mtime_ns]
            for p in sorted((root / "dl").glob("*")) if p.is_file() and not p.is_symlink()}


def restore_download_mtimes(root):
    """A freshly fetched, identical tarball must not invalidate restored products."""
    previous = {}
    for manifest in root.parent.glob("restored-downloads-*.json"):
        for name, state in json.loads(manifest.read_text()).items():
            if Path(name).name != name or "/" in name or "\\" in name:
                raise ValueError("Invalid download manifest path")
            previous.setdefault(name, []).append(state)
    restored = 0
    for name, states in previous.items():
        path = root / "dl" / name
        if not path.is_file() or path.is_symlink():
            continue
        digest, size = file_digest(path), path.stat().st_size
        times = [state[2] for state in states if state[:2] == [digest, size]]
        if times:
            # Both snapshots may have used the same archive at different times.
            # The earliest verified time satisfies both sets of prepared stamps.
            stamp = min(times)
            os.utime(path, ns=(stamp, stamp))
            restored += 1
    print(f"Restored {restored} checksum-verified download timestamps")
    return restored


def configured_keys(root):
    path = root.parent / "keys.env"
    if not path.is_file():
        return {}
    return dict(line.split("=", 1) for line in path.read_text().splitlines() if "=" in line)


def save(root, cache, kind, key):
    entries = products(root, kind)
    cache.mkdir(parents=True, exist_ok=True)
    metadata = {"schema": SCHEMA, "kind": kind, "key": key, "workspace": str(root.resolve()),
                "inputs": source_state(root), "downloads": download_state(root)}
    keys = configured_keys(root)
    metadata.update({name: keys[name] for name in ("toolchain", "build-base") if name in keys})
    # No root signing keys, old configuration, source files, or output images.
    archive = cache / "products.tar.zst"
    subprocess.run(["tar", "--zstd", "-cf", str(archive) + ".tmp", "-C", str(root), *entries],
                   check=True, env={**os.environ, "ZSTD_CLEVEL": "3", "ZSTD_NBTHREADS": "2"})
    os.replace(str(archive) + ".tmp", archive)
    metadata["sha256"] = file_digest(archive)
    (cache / "state.json").write_text(json.dumps(metadata), encoding="utf-8")
    print(f"Saved {kind} cache: {archive.stat().st_size / 1024**2:.0f} MiB")


def restore(root, cache, kind, key):
    state = cache / "state.json"
    archive = cache / "products.tar.zst"
    if not state.is_file() or not archive.is_file():
        return False
    try:
        metadata = json.loads(state.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        print(f"Ignoring damaged {kind} metadata")
        return False
    if any(metadata.get(k) != v for k, v in
           (("schema", SCHEMA), ("kind", kind), ("workspace", str(root.resolve())))):
        print(f"Ignoring incompatible {kind} snapshot")
        return False
    if metadata.get("key") != key:
        print(f"Ignoring incompatible {kind} snapshot")
        return False
    if metadata.get("sha256") != file_digest(archive):
        print(f"Ignoring damaged {kind} snapshot")
        return False
    # Cache products can contain absolute paths, so relocation is a cache miss.
    # Restore before download, which otherwise builds fresh flock/zstd and then
    # has their products replaced by an older snapshot.
    # Each archive owns disjoint children. Restoring targets must never remove
    # or overwrite the separately restored, longer-lived compiler installation.
    for target in product_paths(root, kind):
        if target.is_symlink():
            target.unlink()
        elif target.is_dir():
            shutil.rmtree(target)
        else:
            target.unlink()
    command = ["tar", "--zstd", "-xf", str(archive), "-C", str(root)]
    subprocess.run(command, check=True)
    products(root, kind)
    if kind == "build":
        # Package host builds can install into staging_dir/host (e.g. fwtool),
        # while their installed stamps live in hostpkg. The immutable toolchain
        # snapshot predates those installs. Keep compiled package objects, but
        # let OpenWrt reinstall host packages into both prefixes on restoration.
        stamps = list((root / "staging_dir/hostpkg/stamp").glob(".*_installed"))
        for stamp in stamps:
            stamp.unlink()
        print(f"Scheduled {len(stamps)} host package reinstalls from cached products")
    count = restore_mtimes(root, metadata["inputs"])
    (root.parent / f"restored-downloads-{kind}.json").write_text(
        json.dumps(metadata.get("downloads", {})), encoding="utf-8")
    print(f"Restored {kind} products and {count} unchanged input timestamps")
    return kind


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="operation", required=True)
    for operation in ("save", "restore"):
        command = sub.add_parser(operation)
        command.add_argument("kind", choices=("toolchain", "build"))
        command.add_argument("root", type=Path)
        command.add_argument("cache", type=Path)
        command.add_argument("key")
    sub.add_parser("downloads").add_argument("root", type=Path)
    args = parser.parse_args()
    if args.operation == "downloads":
        restore_download_mtimes(args.root)
    elif args.operation == "save":
        save(args.root, args.cache, args.kind, args.key)
    else:
        restored_kind = restore(args.root, args.cache, args.kind, args.key)
        if restored_kind:
            (args.root.parent / "cache-restored").write_text(restored_kind, encoding="utf-8")


if __name__ == "__main__":
    main()
