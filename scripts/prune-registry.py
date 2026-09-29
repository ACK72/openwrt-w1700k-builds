#!/usr/bin/env python3
"""Remove superseded build-cache registry versions, never a current key's copy.

Refreshing a stable tag leaves the previous manifest untagged. Copies for
earlier compatibility keys are kept for a while in case upstream reverts.
"""
import json
import os
import re
import subprocess
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

UNTAGGED_AGE = timedelta(days=3)
SUPERSEDED_AGE = timedelta(days=14)
MANAGED_TAG = re.compile(r"arm64-v[34]-(?:(?:toolchain|ccache|dl|build)-[a-f0-9]{64}(?:-dl1)?|dl)")


def gh(*args):
    return subprocess.check_output(["gh", *args], text=True, timeout=120)


def current_tags(env):
    return {f"arm64-v3-toolchain-{env['TOOLCHAIN_KEY']}-dl1", f"arm64-v4-ccache-{env['COMPILER_KEY']}",
            f"arm64-v4-build-{env['BUILD_KEY']}", "arm64-v4-dl"}


def removable(version, keep, now):
    tags = version.get("metadata", {}).get("container", {}).get("tags", [])
    age = now - datetime.fromisoformat(version["updated_at"].replace("Z", "+00:00"))
    if not tags:
        return age > UNTAGGED_AGE
    # Unknown tags, including manually pushed ones, are never touched.
    return (not keep.intersection(tags) and all(MANAGED_TAG.fullmatch(tag) for tag in tags)
            and age > SUPERSEDED_AGE)


def main():
    env = os.environ
    owner, name = env["GH_REPO"].split("/", 1)
    scope = "orgs" if json.loads(gh("api", f"users/{owner}"))["type"] == "Organization" else "users"
    base = f"{scope}/{owner}/packages/container/{quote(name.lower() + '/build-cache', safe='')}/versions"
    pages = json.loads(gh("api", "--paginate", "--slurp", f"{base}?per_page=100"))
    now, keep = datetime.now(timezone.utc), current_tags(env)
    removed = 0
    for version in (item for page in pages for item in page):
        if removable(version, keep, now):
            gh("api", "--method", "DELETE", f"{base}/{version['id']}")
            removed += 1
    print(f"Removed {removed} superseded build-cache registry versions")


if __name__ == "__main__":
    try:
        main()
    except (subprocess.SubprocessError, OSError, ValueError, KeyError) as error:
        # Registry cleanup never affects firmware or the caches a build restores.
        print(f"::warning::Registry cleanup skipped: {error}")
