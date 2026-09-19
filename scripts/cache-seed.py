#!/usr/bin/env python3
"""Recover exact ARM64 toolchains and bootstrap caches from immutable OCI artifacts."""
import argparse
import hashlib
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def reference(kind, key):
    if not re.fullmatch(r"[a-f0-9]{64}", key):
        raise ValueError("Invalid seed compatibility key")
    return f"ghcr.io/{os.environ['GITHUB_REPOSITORY'].lower()}/build-cache:arm64-v3-{kind}-{key}"


def resolve(ref):
    result = subprocess.run(["oras", "resolve", ref], text=True, capture_output=True)
    if result.returncode:
        # Missing seeds and unavailable registries both permit a source rebuild.
        print(f"Recovery artifact unavailable: {ref}")
        return None
    value = result.stdout.strip()
    if not re.fullmatch(r"sha256:[a-f0-9]{64}", value):
        raise ValueError("Unexpected registry digest")
    return ref.rsplit(":", 1)[0] + "@" + value


def restore(kind, key, destination):
    ref = resolve(reference(kind, key))
    if not ref:
        return False
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=destination.parent) as temporary:
        stage = Path(temporary)
        subprocess.run(["oras", "pull", ref, "-o", str(stage)], check=True)
        if kind == "toolchain":
            state = json.loads((stage / "state.json").read_text())
            if (state.get("schema"), state.get("kind"), state.get("key")) != (3, kind, key):
                raise ValueError("Incompatible toolchain recovery artifact")
            if digest(stage / "products.tar.zst") != state.get("sha256"):
                raise ValueError("Damaged toolchain recovery artifact")
            destination.mkdir(exist_ok=True)
            for name in ("state.json", "products.tar.zst"):
                os.replace(stage / name, destination / name)
        else:
            state = json.loads((stage / "seed.json").read_text())
            if state.get("kind") != kind or state.get("key") != key or state.get("schema") != 3:
                raise ValueError("Incompatible bootstrap artifact")
            archive = stage / "products.tar.zst"
            if digest(archive) != state.get("sha256"):
                raise ValueError("Damaged bootstrap artifact")
            destination.mkdir(exist_ok=True)
            subprocess.run(["tar", "--zstd", "-xf", str(archive), "-C", str(destination)], check=True)
    print(f"Recovered {kind} from {ref}")
    return True


def publish(kind, key, source):
    ref = reference(kind, key)
    if resolve(ref):
        print(f"Keeping existing immutable {kind} recovery artifact")
        return
    if not source.is_dir() or not any(source.iterdir()):
        raise ValueError("Cannot publish an empty recovery artifact")
    with tempfile.TemporaryDirectory(dir=source.parent) as temporary:
        stage = Path(temporary)
        if kind == "toolchain":
            # Upload in place; do not make another gigabyte-sized copy.
            stage = source
            files = ["products.tar.zst:application/zstd", "state.json:application/json"]
        else:
            archive = stage / "products.tar.zst"
            subprocess.run(["tar", "--zstd", "-cf", str(archive.resolve()), "-C", str(source), "."],
                           check=True, env={**os.environ, "ZSTD_CLEVEL": "1", "ZSTD_NBTHREADS": "2"})
            (stage / "seed.json").write_text(json.dumps({"schema": 3, "kind": kind, "key": key,
                                                        "sha256": digest(archive)}))
            files = ["products.tar.zst:application/zstd", "seed.json:application/json"]
        subprocess.run(["oras", "push", ref, "--artifact-type", "application/vnd.w1700k.cache.v3",
                        "--annotation", "org.opencontainers.image.source=https://github.com/" + os.environ["GITHUB_REPOSITORY"],
                        *files], cwd=stage, check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("restore", "publish"))
    parser.add_argument("kind", choices=("toolchain", "ccache", "dl"))
    parser.add_argument("key")
    parser.add_argument("path", type=Path)
    args = parser.parse_args()
    try:
        (restore if args.operation == "restore" else publish)(args.kind, args.key, args.path.resolve())
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        # Recovery storage is optional. Exact keys and archive checks still apply.
        print(f"::warning::{args.kind} recovery {args.operation} failed: {error}")


if __name__ == "__main__":
    main()
