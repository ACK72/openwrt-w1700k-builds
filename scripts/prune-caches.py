#!/usr/bin/env python3
"""Remove superseded cache generations only after confirming the replacement."""
import json
import os
import subprocess
from urllib.parse import quote


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
    env = os.environ
    prefix, repo, ref = env["CACHE_PREFIX"], env["GH_REPO"], env["GITHUB_REF"]
    run = f"{env['GITHUB_RUN_ID']}-{env['GITHUB_RUN_ATTEMPT']}"
    replacements = {"dl": f"{prefix}-dl-{run}",
                    "ccache": f"{prefix}-ccache-{env['TOOLCHAIN_KEY']}-{run}",
                    "build": f"{prefix}-build-{env['BUILD_KEY']}-{run}",
                    "toolchain": f"{prefix}-toolchain-{env['TOOLCHAIN_KEY']}",
                    "npu": f"{prefix}-npu-{env['NPU_KEY']}"}
    raw = subprocess.check_output(["gh", "api", "--paginate", "--slurp",
                                   f"repos/{repo}/actions/caches?per_page=100&ref={quote(ref, safe='')}"], text=True)
    items = [item for page in json.loads(raw) for item in page["actions_caches"]]
    for cache_id in candidates(items, prefix, replacements, ref):
        subprocess.run(["gh", "api", "--method", "DELETE", f"repos/{repo}/actions/caches/{cache_id}"], check=True)
        print(f"Removed superseded cache {cache_id}")


if __name__ == "__main__":
    main()
