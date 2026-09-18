#!/usr/bin/env python3
"""Manually promote the latest successful RC, reusing its exact ITB bytes."""
import argparse
import importlib.util
import json
import os
import subprocess
from pathlib import Path

import release

spec = importlib.util.spec_from_file_location("source_stack", Path(__file__).with_name("source-stack.py"))
stack = importlib.util.module_from_spec(spec)
spec.loader.exec_module(stack)


def select_candidate(repo):
    runs = json.loads(release.gh("api", f"repos/{repo}/actions/workflows/build.yml/runs?branch=main&per_page=1"))["workflow_runs"]
    if not runs or runs[0].get("status") != "completed" or runs[0].get("conclusion") != "success":
        raise ValueError("The latest RC workflow must have completed successfully; a failed, cancelled or pending run blocks promotion")
    latest = runs[0]
    items = sorted((item for item in release.releases(repo) if release.managed(item)
                    and release.channel(item) == release.RC and not item.get("draft")),
                   key=lambda item: (item.get("published_at") or "", item["id"]), reverse=True)
    if not items or not release.complete(items[0]):
        raise ValueError("No complete RC prerelease is available")
    candidate = items[0]
    data = release.provenance(candidate)
    run = json.loads(release.gh("api", f"repos/{repo}/actions/runs/{data['run_id']}"))
    for item in (latest, run):
        if (item.get("status") != "completed" or item.get("conclusion") != "success"
                or item.get("head_branch") != "main" or item.get("head_sha") != data["builder_commit"]
                or item.get("path", "").split("@", 1)[0] != ".github/workflows/build.yml"):
            raise ValueError("RC provenance does not match a successful build on main")
    if int(data["build_attempt"]) > run.get("run_attempt", 0):
        raise ValueError("RC provenance refers to an unknown build attempt")
    # A successful unchanged-input check may reuse the same already published RC.
    return candidate, data


def source_checkout(root, data):
    root.mkdir(parents=True)
    stack.git(root, "init")
    stack.git(root, "remote", "add", "origin", stack.repository_url("openwrt"))
    stack.git(root, "fetch", "--filter=blob:none", "--no-tags", "origin",
              f"refs/heads/{stack.RC}", f"refs/tags/{data['source_tag']}:refs/tags/{data['source_tag']}")
    if stack.remote_head(root, stack.RC) != data["source"]:
        raise ValueError("The RC branch no longer matches the successful RC image")
    if stack.git(root, "rev-parse", data["source_tag"] + "^{commit}") != data["source"]:
        raise ValueError("The RC source snapshot does not match the image")
    snapshot = json.loads(stack.git(root, "for-each-ref", "--format=%(contents)", "refs/tags/" + data["source_tag"]))
    for key in ("source", "builder_commit", "upstream", "fanboy", "patch_digest"):
        if snapshot.get(key) != data.get(key):
            raise ValueError("Source snapshot provenance does not match the RC")
    return stack.remote_head(root, stack.STABLE)


def move_stable(root, expected, target):
    stack.push(root, f"--force-with-lease=refs/heads/{stack.STABLE}:{expected}",
               "origin", f"{target}:refs/heads/{stack.STABLE}")


def promote(repo, work):
    if os.environ.get("GITHUB_EVENT_NAME") != "workflow_dispatch":
        raise ValueError("Stable promotion requires an explicit workflow_dispatch")
    candidate, data = select_candidate(repo)
    if work.exists():
        raise ValueError("Promotion requires a new disposable directory")
    work.mkdir(parents=True)
    source = work / "source"
    previous = source_checkout(source, data)
    if previous:
        stack.git(source, "fetch", "--no-tags", "origin", previous)
    downloads, output = work / "download", work / "assets"
    downloads.mkdir()
    output.mkdir()
    asset = candidate["assets"][0]
    release.gh("release", "download", candidate["tag_name"], "--repo", repo,
               "--pattern", asset["name"], "--dir", str(downloads))
    image = downloads / asset["name"]
    if not release.matching_asset(asset, image, "sha256:" + release.sha256(image)):
        raise ValueError("Downloaded RC image differs from the published asset")
    with image.open("rb") as stream:
        if stream.read(4) != bytes.fromhex("d00dfeed"):
            raise ValueError("RC asset is not a FIT sysupgrade image")
    name = asset["name"].replace(release.RC + "-r", release.STABLE + "-r", 1)
    image.rename(output / name)
    tag = f"{release.STABLE}-{data['run_id']}-{data['build_attempt']}"
    title = candidate["name"].replace(release.RC + "_", release.STABLE + "_", 1)
    body = candidate["body"].replace("## " + candidate["name"], "## " + title, 1)
    body += f"\nPromoted from [{candidate['tag_name']}](https://github.com/{repo}/releases/tag/{candidate['tag_name']}); identical image SHA-256.\n"
    staged = release.stage_release(output, repo, tag, title, body, release.STABLE)
    # Recheck after downloading/uploading; manual source changes or a newly queued
    # RC run must not turn an older build into the newly promoted release.
    current, current_data = select_candidate(repo)
    if current["id"] != candidate["id"] or current_data != data or stack.remote_head(source, stack.RC) != data["source"]:
        raise ValueError("RC changed during promotion; rerun after the latest build completes")
    move_stable(source, previous, data["source"])
    try:
        published = release.finish_release(repo, staged, title, body, release.STABLE)
    except Exception:
        # Do not roll back after an uncertain publication response: reconcile first.
        observed = json.loads(release.gh("api", f"repos/{repo}/releases/{staged['id']}"))
        if observed.get("draft"):
            move_stable(source, data["source"], previous)
            raise
        if not release.publication_matches(staged, observed):
            raise RuntimeError("Published stable release differs from the verified RC; manual recovery is required")
        published = observed
    release.prune(repo, published)
    print(f"Promoted {data['source']}: https://github.com/{repo}/releases/tag/{tag}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("work", type=Path)
    args = parser.parse_args()
    promote(os.environ["GH_REPO"], args.work)


if __name__ == "__main__":
    main()
