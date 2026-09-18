#!/usr/bin/env python3
"""Budget cache uploads below the free allowance and remove old generations."""
import argparse
import json
import os
import re
import subprocess
from pathlib import Path
from urllib.parse import quote

# Decimal GB leaves headroom below either interpretation of GitHub's 10 GB.
BUDGET = 9_000_000_000
MANAGED = re.compile(r"w1700k-v2-(?:Linux-(?:X64|ARM64)-(?:dl|ccache|build|toolchain|npu)|shared-distfeeds)-")
SHARED_PREFIX = "w1700k-v2-shared"


def list_caches(repo, ref=None):
    query = "?per_page=100" + (f"&ref={quote(ref, safe='')}" if ref else "")
    raw = subprocess.check_output(["gh", "api", "--paginate", "--slurp",
                                   f"repos/{repo}/actions/caches{query}"], text=True, timeout=120)
    return [item for page in json.loads(raw) for item in page["actions_caches"]]


def upload_bound(path):
    if not path.is_dir() or path.is_symlink():
        raise ValueError("Expected a cache directory")
    # Bound tar headers/padding and possible compression expansion, even for
    # already compressed .zst snapshots. Hard links are conservatively counted.
    size = 10240
    for item in path.rglob("*"):
        size += 1024
        if item.is_file() and not item.is_symlink():
            size += ((item.stat().st_size + 511) // 512) * 512
    return size + size // 50 + 64 * 1024**2


def reservation_plan(items, reservations, incoming, size, family, ref, budget=BUDGET):
    """Return eviction IDs, or None if saving cannot fit without protected data."""
    if size > budget:
        return None
    present = {item["key"] for item in items if item["ref"] == ref}
    # A completed cache upload can take time to appear in the REST listing.
    # Keep earlier reservations until the API accounts for them, and never
    # evict anything saved in this run merely to save a lower-priority cache.
    total = sum(item["size_in_bytes"] for item in items)
    total += sum(value for key, value in reservations.items() if key not in present)
    total += size
    eligible = sorted((item for item in items
                       if item["ref"] == ref and MANAGED.match(item["key"])
                       and item["key"] not in reservations and item["key"] != incoming),
                      key=lambda item: (not item["key"].startswith(family),
                                        item.get("last_accessed_at", ""), item["id"]))
    remove = []
    for item in eligible:
        if total <= budget:
            break
        remove.append(item["id"])
        total -= item["size_in_bytes"]
    return remove if total <= budget else None


def reserve(kind, path, key):
    env = os.environ
    repo, ref, prefix = env["GH_REPO"], env["GITHUB_REF"], env["CACHE_PREFIX"]
    if kind == "distfeeds":
        prefix = SHARED_PREFIX
    family = f"{prefix}-{kind}-"
    if not MANAGED.match(key) or not key.startswith(family):
        raise ValueError("Unexpected cache namespace")
    ledger = Path(".work/cache-budget.json")
    reservations = json.loads(ledger.read_text()) if ledger.exists() else {}
    items = list_caches(repo)
    if any(item["key"] == key and item["ref"] == ref for item in items):
        print(f"Cache already exists: {key}")
        return False
    size = upload_bound(path)
    remove = reservation_plan(items, reservations, key, size, family, ref)
    current = sum(item["size_in_bytes"] for item in items)
    print(f"Cache budget: existing {current / 1e9:.3f} GB, upload bound {size / 1e9:.3f} GB, limit {BUDGET / 1e9:.1f} GB")
    if remove is None:
        print(f"::warning::Skipping {kind} cache: free storage budget cannot accommodate it")
        return False
    if kind in ("npu", "distfeeds") and any(item["id"] in remove and not item["key"].startswith(family) for item in items):
        # These small caches are saved before compiler/kernel caches are restored.
        print(f"Skipping {kind} cache to preserve build caches until restoration")
        return False
    for cache_id in remove:
        subprocess.run(["gh", "api", "--method", "DELETE", f"repos/{repo}/actions/caches/{cache_id}"],
                       check=True, timeout=60)
        print(f"Removed old cache {cache_id} before upload to stay within the free allowance")
    # All cache families have been restored before large snapshots are saved.
    # This may replace the previous snapshot before upload; an upload failure
    # can reduce cache reuse, but must not cause over-budget storage or bad firmware.
    reservations[key] = size
    ledger.parent.mkdir(parents=True, exist_ok=True)
    ledger.write_text(json.dumps(reservations))
    return True


def candidates(items, prefix, replacements, ref):
    result = []
    for kind, replacement in replacements.items():
        if not any(item["key"] == replacement and item["ref"] == ref for item in items):
            continue
        result.extend(item["id"] for item in items
                      if item["ref"] == ref and item["key"].startswith(f"{prefix}-{kind}-")
                      and item["key"] != replacement)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command")
    allocate = sub.add_parser("reserve")
    allocate.add_argument("kind", choices=("npu", "toolchain", "build", "dl", "ccache", "distfeeds"))
    allocate.add_argument("path", type=Path)
    allocate.add_argument("key")
    args = parser.parse_args()
    if args.command == "reserve":
        try:
            save = reserve(args.kind, args.path, args.key)
        except (subprocess.SubprocessError, OSError, json.JSONDecodeError) as error:
            print(f"::warning::Cache storage could not be verified; skipping upload: {error}")
            save = False
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
            output.write(f"save={str(save).lower()}\n")
        return
    env = os.environ
    prefix, repo, ref = env["CACHE_PREFIX"], env["GH_REPO"], env["GITHUB_REF"]
    run = f"{env['GITHUB_RUN_ID']}-{env['GITHUB_RUN_ATTEMPT']}"
    replacements = {"dl": f"{prefix}-dl-{run}",
                    "ccache": f"{prefix}-ccache-{env['TOOLCHAIN_KEY']}-{run}",
                    "build": f"{prefix}-build-{env['BUILD_KEY']}-{run}",
                    "toolchain": f"{prefix}-toolchain-{env['TOOLCHAIN_KEY']}-{run}",
                    "npu": f"{prefix}-npu-{env['NPU_KEY']}"}
    items = list_caches(repo, ref)
    remove = candidates(items, prefix, replacements, ref)
    if env.get("DISTFEEDS_CACHE_KEY"):
        remove += candidates(items, SHARED_PREFIX, {"distfeeds": env["DISTFEEDS_CACHE_KEY"]}, ref)
    for cache_id in remove:
        subprocess.run(["gh", "api", "--method", "DELETE", f"repos/{repo}/actions/caches/{cache_id}"], check=True)
        print(f"Removed superseded cache {cache_id}")
    current = list_caches(repo)
    used = sum(item["size_in_bytes"] for item in current)
    message = f"Actions cache storage: {used / 1e9:.3f} GB in {len(current)} entries; upload budget {BUDGET / 1e9:.1f} GB."
    print(message)
    if env.get("GITHUB_STEP_SUMMARY"):
        with open(env["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as summary:
            summary.write(message + "\n")


if __name__ == "__main__":
    main()
