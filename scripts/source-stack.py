#!/usr/bin/env python3
"""Compose upstream + fanboy + W1700K patches; publish with explicit leases."""
import argparse
import base64
import hashlib
import json
import os
import re
import shlex
import subprocess
import tempfile
from pathlib import Path
from urllib.request import urlopen
from repositories import repository_url

ROOT = Path(__file__).resolve().parents[1]
UPSTREAM_REPO = "https://github.com/openwrt/openwrt.git"
FANBOY_REPO = "https://github.com/OpenWRT-fanboy/OpenW1700k.git"
RC = "w1700k-oc-rc"
STABLE = "w1700k-oc"
SHA = re.compile(r"[a-f0-9]{40}\Z")


def git(root, *args, env=None):
    return subprocess.check_output(["git", "-C", str(root), *args], text=True,
                                   env=env, encoding="utf-8").strip()


def auth_env():
    token = os.environ.get("OPENWRT_TOKEN", "")
    if not token:
        raise ValueError("Configure a deploy key or OPENWRT_TOKEN for the OpenWrt source repository")
    env = os.environ.copy()
    env.update(GIT_CONFIG_COUNT="1", GIT_CONFIG_KEY_0="http.https://github.com/.extraheader",
               GIT_CONFIG_VALUE_0="AUTHORIZATION: basic " + base64.b64encode(("x-access-token:" + token).encode()).decode())
    return env


def push(root, *args):
    key = os.environ.get("OPENWRT_SSH_KEY")
    if not key:
        return git(root, "push", *args, env=auth_env())
    # The deploy key can write only the OpenWrt source repo. Keep it outside the source,
    # artifacts and build jobs, and verify GitHub's host key over HTTPS.
    with tempfile.TemporaryDirectory(prefix="w1700k-ssh-", dir=os.environ.get("RUNNER_TEMP")) as directory:
        private, known = Path(directory) / "key", Path(directory) / "known_hosts"
        private.write_text(key.rstrip() + "\n", encoding="utf-8")
        private.chmod(0o600)
        with urlopen("https://api.github.com/meta", timeout=30) as response:
            host_keys = json.load(response)["ssh_keys"]
        known.write_text("".join("github.com " + value + "\n" for value in host_keys), encoding="utf-8")
        env = os.environ.copy()
        env["GIT_SSH_COMMAND"] = shlex.join(["ssh", "-i", str(private), "-o", "IdentitiesOnly=yes",
                                             "-o", "StrictHostKeyChecking=yes", "-o", "UserKnownHostsFile=" + str(known)])
        push_url = repository_url("openwrt").replace("https://github.com/", "git@github.com:")
        return git(root, "-c", "remote.origin.pushurl=" + push_url, "push", *args, env=env)


def remote_head(root, branch):
    result = git(root, "ls-remote", "origin", "refs/heads/" + branch)
    return result.split()[0] if result else ""


def checkout(root, source, upstream, fanboy):
    if root.exists():
        raise ValueError("Source composition requires a new disposable directory")
    root.mkdir(parents=True)
    git(root, "init")
    git(root, "config", "core.autocrlf", "false")
    git(root, "config", "user.name", "github-actions[bot]")
    git(root, "config", "user.email", "41898282+github-actions[bot]@users.noreply.github.com")
    for name, url in (("origin", source), ("upstream", upstream), ("fanboy", fanboy)):
        git(root, "remote", "add", name, url)
    # Freeze the vendor first, then obtain the official history containing its base.
    git(root, "fetch", "--filter=blob:none", "--no-tags", "fanboy", "+refs/heads/ubi2-oc:refs/remotes/fanboy/ubi2-oc")
    git(root, "fetch", "--filter=blob:none", "--no-tags", "upstream", "+refs/heads/main:refs/remotes/upstream/main")


def compose(root, patches, builder, source=None, upstream=UPSTREAM_REPO, fanboy=FANBOY_REPO):
    if not SHA.fullmatch(builder):
        raise ValueError("The builder revision must be an exact commit")
    checkout(root, source or repository_url("openwrt"), upstream, fanboy)
    heads = {name: remote_head(root, name) for name in ("main", "ubi2-oc", RC)}
    official = git(root, "rev-parse", "refs/remotes/upstream/main")
    vendor = git(root, "rev-parse", "refs/remotes/fanboy/ubi2-oc")
    bases = git(root, "merge-base", "--all", official, vendor).splitlines()
    if len(bases) != 1:
        raise ValueError("Ambiguous fanboy patch base")
    base = bases[0]
    span = f"{base}..{vendor}"
    if git(root, "rev-list", "--merges", span):
        raise ValueError("Fanboy patch stack contains merges; review its boundary")
    commits = git(root, "rev-list", "--reverse", span).splitlines()
    # A rewritten official history must never silently become vendor patches.
    if heads["main"]:
        git(root, "fetch", "--filter=blob:none", "--no-tags", "origin", heads["main"])
        git(root, "merge-base", "--is-ancestor", heads["main"], official)
    git(root, "checkout", "--detach", official)
    mapping = []
    for commit in commits:
        env = os.environ.copy()
        env["GIT_COMMITTER_DATE"] = git(root, "show", "-s", "--format=%cI", commit)
        # Empty or conflicting commits stop the run instead of losing changes.
        git(root, "cherry-pick", "-x", commit, env=env)
        mapping.append({"original": commit, "applied": git(root, "rev-parse", "HEAD")})
    vendor_result = git(root, "rev-parse", "HEAD")
    series = json.loads((patches / "series.json").read_text(encoding="utf-8"))
    local_patches = []
    digest = hashlib.sha256()
    for entry in series["patches"]:
        name = entry["file"]
        if Path(name).name != name or not name.endswith(".patch"):
            raise ValueError("Invalid patch filename")
        path = patches / name
        if path.is_symlink():
            raise ValueError("Patch files cannot be symlinks")
        content = path.read_bytes()
        digest.update(name.encode() + b"\0" + content + b"\0")
        git(root, "am", "--3way", "--committer-date-is-author-date", str(path.resolve()))
        local_patches.append({**entry, "applied": git(root, "rev-parse", "HEAD"),
                    "sha256": hashlib.sha256(content).hexdigest()})
    result = {"schema": 1, "upstream": official, "fanboy": vendor, "fanboy_base": base,
              "fanboy_result": vendor_result, "fanboy_commits": mapping, "local_patches": local_patches,
              "patch_digest": digest.hexdigest(), "builder_commit": builder,
              "source": git(root, "rev-parse", "HEAD"), "previous": heads}
    git(root, "diff", "--exit-code", "HEAD")
    return result


def publish(root, manifest, run_id, attempt):
    if not re.fullmatch(r"[0-9]+", run_id) or not re.fullmatch(r"[0-9]+", attempt):
        raise ValueError("Invalid workflow identity")
    snapshot = f"w1700k-oc-rc-source-{run_id}-{attempt}"
    manifest["source_tag"] = snapshot
    git(root, "tag", "-a", snapshot, manifest["source"], "-m", json.dumps(manifest, sort_keys=True))
    # Keep vendor objects reachable even after its next force push.
    vendor_tag = "sources/fanboy/" + manifest["fanboy"]
    git(root, "tag", vendor_tag, manifest["fanboy"])
    refs = {"main": manifest["upstream"], "ubi2-oc": manifest["fanboy"], RC: manifest["source"]}
    archives = []
    for branch, previous in manifest["previous"].items():
        if previous:
            git(root, "fetch", "--filter=blob:none", "--no-tags", "origin", previous)
            archive = f"sources/previous/{branch}/{previous}"
            git(root, "tag", archive, previous)
            archives.append("refs/tags/" + archive)
    leases = [f"--force-with-lease=refs/heads/{name}:{manifest['previous'][name]}" for name in refs]
    push(root, "--atomic", *leases, "origin",
        *(f"{sha}:refs/heads/{name}" for name, sha in refs.items()),
        f"refs/tags/{snapshot}", f"refs/tags/{vendor_tag}", *archives)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("work", type=Path)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--publish", action="store_true")
    args = parser.parse_args()
    builder = os.environ.get("GITHUB_SHA") or git(ROOT, "rev-parse", "HEAD")
    result = compose(args.work, ROOT / "patches/w1700k", builder)
    if args.publish:
        publish(args.work, result, os.environ["GITHUB_RUN_ID"], os.environ["GITHUB_RUN_ATTEMPT"])
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"source={result['source']}")
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
            output.write(f"source={result['source']}\nsource-tag={result.get('source_tag', '')}\n")


if __name__ == "__main__":
    main()
