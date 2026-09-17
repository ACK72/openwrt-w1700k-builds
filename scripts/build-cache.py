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

SOURCE_ROOTS = ("tools", "toolchain", "include", "config", "target", "scripts", "package", "feeds")
ROOT_INPUTS = ("Makefile", "rules.mk", "Config.in", ".config", "feeds.conf")
SCHEMA = 2


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


def products(root, kind):
    if kind == "build":
        paths = [root / "build_dir", root / "staging_dir"]
    else:
        paths = [root / "build_dir/host", root / "staging_dir/host"]
        paths += sorted(root.glob("build_dir/toolchain-*"))
        paths += sorted(root.glob("staging_dir/toolchain-*"))
    if len(paths) < (2 if kind == "build" else 4) or any(not p.is_dir() or p.is_symlink() for p in paths):
        raise RuntimeError("Incomplete build products; refusing to save cache")
    return [p.relative_to(root).as_posix() for p in paths]


def save(root, cache, kind, key):
    entries = products(root, kind)
    cache.mkdir(parents=True, exist_ok=True)
    metadata = {"schema": SCHEMA, "kind": kind, "key": key, "workspace": str(root.resolve()),
                "inputs": source_state(root)}
    # No root signing keys, old configuration, source files, or output images.
    archive = cache / "products.tar.zst"
    subprocess.run(["tar", "--zstd", "-cf", str(archive) + ".tmp", "-C", str(root), *entries],
                   check=True, env={**os.environ, "ZSTD_CLEVEL": "3", "ZSTD_NBTHREADS": "2"})
    os.replace(str(archive) + ".tmp", archive)
    (cache / "state.json").write_text(json.dumps(metadata), encoding="utf-8")
    print(f"Saved {kind} cache: {archive.stat().st_size / 1024**2:.0f} MiB")


def restore(root, cache, kind, key):
    state = cache / "state.json"
    archive = cache / "products.tar.zst"
    if not state.is_file() or not archive.is_file():
        return False
    metadata = json.loads(state.read_text(encoding="utf-8"))
    if any(metadata.get(k) != v for k, v in
           (("schema", SCHEMA), ("kind", kind), ("key", key), ("workspace", str(root.resolve())))):
        print(f"Ignoring incompatible {kind} snapshot")
        return False
    # Cache products can contain absolute paths, so relocation is a cache miss.
    # Restore before download, which otherwise builds fresh flock/zstd and then
    # has their products replaced by an older snapshot.
    for name in ("build_dir", "staging_dir"):
        target = root / name
        if target.is_symlink():
            raise RuntimeError(f"Unexpected build directory symlink: {target}")
        if target.exists():
            shutil.rmtree(target)
    subprocess.run(["tar", "--zstd", "-xf", str(archive), "-C", str(root)], check=True)
    count = restore_mtimes(root, metadata["inputs"])
    print(f"Restored {kind} products and {count} unchanged input timestamps")
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("save", "restore"))
    parser.add_argument("kind", choices=("toolchain", "build"))
    parser.add_argument("root", type=Path)
    parser.add_argument("cache", type=Path)
    parser.add_argument("key")
    args = parser.parse_args()
    if args.operation == "save":
        save(args.root, args.cache, args.kind, args.key)
    elif restore(args.root, args.cache, args.kind, args.key):
        (args.root.parent / "cache-restored").write_text(args.kind, encoding="utf-8")


if __name__ == "__main__":
    main()
