#!/usr/bin/env python3
"""Keep checksummed build caches in GHCR, independent of the Actions cache.

Actions caches are immutable, capped per repository and evicted when unused.
These OCI artifacts in the repository's container package outlive both: a
toolchain snapshot is immutable per key, while compiler, download and build
state copies are refreshed under a stable tag when missing, stale, or refused
by the Actions cache budget.
"""
import argparse
import hashlib
import json
import os
import re
import subprocess
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

KEY = re.compile(r"[a-f0-9]{64}")
SNAPSHOTS = ("toolchain", "build")
SHARED_DL = "shared"


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def repository():
    return f"ghcr.io/{os.environ['GITHUB_REPOSITORY'].lower()}/build-cache"


def checked(key):
    if not KEY.fullmatch(key or ""):
        raise ValueError("Invalid cache compatibility key")
    return key


def reference(kind, key):
    if kind == "toolchain":
        # Immutable complete snapshots keep their established v3 tags.
        return f"{repository()}:arm64-v3-toolchain-{checked(key)}-dl1"
    if kind == "dl":
        # Source archives are verified by OpenWrt hashes, not by toolchain.
        return f"{repository()}:arm64-v4-dl"
    return f"{repository()}:arm64-v4-{kind}-{checked(key)}"


def expected_key(kind, key):
    return SHARED_DL if kind == "dl" else key


def candidates(kind, key, legacy):
    """Current copy first, then earlier seeds with the key their metadata records."""
    result = [(reference(kind, key), expected_key(kind, key))]
    if kind == "toolchain":
        result.append((reference(kind, key).removesuffix("-dl1"), key))
    elif kind in ("ccache", "dl") and legacy:
        # First-run seeds from before compiler-keyed copies used toolchain keys.
        result.append((f"{repository()}:arm64-v3-{kind}-{checked(legacy)}", legacy))
    return result


def resolve(ref):
    result = subprocess.run(["oras", "resolve", ref], text=True, capture_output=True)
    if result.returncode:
        # Missing copies and unavailable registries both permit a source rebuild.
        print(f"Registry copy unavailable: {ref}")
        return None
    value = result.stdout.strip()
    if not re.fullmatch(r"sha256:[a-f0-9]{64}", value):
        raise ValueError("Unexpected registry digest")
    return ref.rsplit(":", 1)[0] + "@" + value


def created(ref):
    manifest = json.loads(subprocess.check_output(["oras", "manifest", "fetch", ref], text=True))
    value = manifest.get("annotations", {}).get("org.opencontainers.image.created", "")
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def restore(kind, key, destination, legacy=None):
    for candidate, state_key in candidates(kind, key, legacy):
        ref = resolve(candidate)
        if ref:
            break
    else:
        return False
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=destination.parent) as temporary:
        stage = Path(temporary)
        subprocess.run(["oras", "pull", ref, "-o", str(stage)], check=True)
        if kind in SNAPSHOTS:
            state = json.loads((stage / "state.json").read_text())
            if (state.get("schema"), state.get("kind"), state.get("key")) != (3, kind, key):
                raise ValueError(f"Incompatible {kind} registry copy")
            if digest(stage / "products.tar.zst") != state.get("sha256"):
                raise ValueError(f"Damaged {kind} registry copy")
            destination.mkdir(exist_ok=True)
            # Invalidate old metadata before replacing its archive.
            (destination / "state.json").unlink(missing_ok=True)
            for name in ("products.tar.zst", "state.json"):
                os.replace(stage / name, destination / name)
        else:
            state = json.loads((stage / "seed.json").read_text())
            if (state.get("schema") not in (3, 4) or state.get("kind") != kind
                    or state.get("key") != state_key):
                raise ValueError(f"Incompatible {kind} registry copy")
            archive = stage / "products.tar.zst"
            if digest(archive) != state.get("sha256"):
                raise ValueError(f"Damaged {kind} registry copy")
            destination.mkdir(exist_ok=True)
            subprocess.run(["tar", "--zstd", "-xf", str(archive), "-C", str(destination)], check=True)
    print(f"Recovered {kind} from {ref}")
    return True


def push(ref, stage, files):
    subprocess.run(["oras", "push", ref, "--artifact-type", "application/vnd.w1700k.cache.v3",
                    "--annotation", "org.opencontainers.image.source=https://github.com/" + os.environ["GITHUB_REPOSITORY"],
                    *files], cwd=stage, check=True)


def publish(kind, key, source, max_age=None, force=False):
    """Push when missing; mutable copies also when stale or forced."""
    ref = reference(kind, key)
    existing = resolve(ref)
    if existing and kind == "toolchain":
        print("Keeping existing immutable toolchain registry copy")
        return
    if existing and not force:
        stamp = created(existing) if max_age is not None else None
        if max_age is None or (stamp and datetime.now(timezone.utc) - stamp < timedelta(days=max_age)):
            print(f"Keeping current {kind} registry copy ({stamp or 'no refresh interval'})")
            return
    if not source.is_dir() or not any(source.iterdir()):
        raise ValueError(f"Cannot publish an empty {kind} registry copy")
    if kind in SNAPSHOTS:
        state = json.loads((source / "state.json").read_text())
        if (state.get("kind"), state.get("key")) != (kind, key) or state.get("complete") is False:
            # Interrupted progress stays in the Actions cache only.
            print(f"Not publishing an incomplete or foreign {kind} snapshot")
            return
        if digest(source / "products.tar.zst") != state.get("sha256"):
            raise ValueError(f"Refusing to publish a damaged {kind} snapshot")
        # Upload in place; do not make another gigabyte-sized copy.
        push(ref, source, ["products.tar.zst:application/zstd", "state.json:application/json"])
    else:
        with tempfile.TemporaryDirectory(dir=source.parent) as temporary:
            stage = Path(temporary)
            archive = stage / "products.tar.zst"
            subprocess.run(["tar", "--zstd", "-cf", str(archive.resolve()), "-C", str(source), "."],
                           check=True, env={**os.environ, "ZSTD_CLEVEL": "1",
                                            "ZSTD_NBTHREADS": str(os.cpu_count() or 2)})
            (stage / "seed.json").write_text(json.dumps({"schema": 4, "kind": kind,
                                                        "key": expected_key(kind, key),
                                                        "sha256": digest(archive)}))
            push(ref, stage, ["products.tar.zst:application/zstd", "seed.json:application/json"])
    print(f"Published {kind} registry copy: {ref}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("restore", "publish"))
    parser.add_argument("kind", choices=("toolchain", "build", "ccache", "dl"))
    parser.add_argument("key", help="compatibility key; '-' for shared downloads")
    parser.add_argument("path", type=Path)
    parser.add_argument("--legacy", help="toolchain key of an earlier first-run seed")
    parser.add_argument("--max-age", type=float, help="refresh a mutable copy older than DAYS")
    parser.add_argument("--force", action="store_true", help="replace a mutable copy now")
    args = parser.parse_args()
    key = None if args.kind == "dl" else args.key
    try:
        if args.operation == "restore":
            restore(args.kind, key, args.path.resolve(), args.legacy)
        else:
            publish(args.kind, key, args.path.resolve(), args.max_age, args.force)
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        # Registry storage is optional. Exact keys and archive checks still apply.
        print(f"::warning::{args.kind} registry {args.operation} failed: {error}")


if __name__ == "__main__":
    main()
