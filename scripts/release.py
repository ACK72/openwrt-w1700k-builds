#!/usr/bin/env python3
"""Validate W1700K images, publish complete releases, then retain the newest three."""
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote

PREFIX = "w1700k-ubi2-oc-"
TAG = re.compile(r"w1700k-ubi2-oc-[0-9]+-[0-9]+\Z")
DEVICE = "gemtek_w1700k-ubi"
SUPPORTED_DEVICE = "gemtek,w1700k-ubi"
TARGET = "airoha/an7581"
MARKER = "<!-- w1700k-release:v1 -->"
IMAGE_PREFIX = "openwrt-airoha-an7581-gemtek_w1700k-ubi-squashfs-sysupgrade-"
RELEASE_IMAGE = re.compile(re.escape(IMAGE_PREFIX) + r"r[0-9]+\.itb\Z")


def firmware_revision(root):
    profiles = json.loads((root / "firmware/profiles.json").read_text(encoding="utf-8"))
    revision = profiles["version_code"]
    if not re.fullmatch(r"r[0-9]+-[a-f0-9]+", revision):
        raise ValueError("Invalid firmware revision")
    return revision


def sha256(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def verify_image(target, metadata_file):
    profiles = json.loads((target / "profiles.json").read_text(encoding="utf-8"))
    metadata = json.loads(metadata_file.read_text(encoding="utf-8"))
    if profiles.get("target") != TARGET or metadata.get("version", {}).get("target") != TARGET:
        raise ValueError("Wrong firmware target")
    profile = profiles.get("profiles", {}).get(DEVICE, {})
    devices = metadata.get("new_supported_devices", metadata.get("supported_devices", []))
    if SUPPORTED_DEVICE not in devices or SUPPORTED_DEVICE not in profile.get("supported_devices", []):
        raise ValueError("Image does not support W1700K UBI")
    if metadata.get("compat_version") != "2.0":
        raise ValueError("Unexpected UBI partition compatibility version")
    images = [item for item in profile.get("images", []) if item.get("type") == "sysupgrade"]
    if len(images) != 1:
        raise ValueError("Expected exactly one sysupgrade image in profiles.json")
    item = images[0]
    name = item["name"]
    if Path(name).name != name or "/" in name or "\\" in name or not name.endswith("-sysupgrade.itb"):
        raise ValueError("Invalid sysupgrade image filename")
    image = target / name
    if image.is_symlink() or image.stat().st_size != item["size"] or sha256(image) != item["sha256"]:
        raise ValueError("Image size/checksum does not match profiles.json")
    with image.open("rb") as stream:
        if stream.read(4) != bytes.fromhex("d00dfeed"):
            raise ValueError("Invalid FIT image magic")
    if len(list(target.glob("*sysupgrade.itb"))) != 1:
        raise ValueError("Unexpected extra sysupgrade images")
    return image


def verify_checksums(root):
    entries = (root / "SHA256SUMS").read_text(encoding="utf-8").splitlines()
    if not entries:
        raise ValueError("Empty checksum list")
    covered = set()
    for line in entries:
        digest, name = line.split("  ", 1)
        path = root / name
        if not re.fullmatch(r"[a-f0-9]{64}", digest) or Path(name).is_absolute() or path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
            raise ValueError("Invalid checksum entry")
        canonical = path.resolve()
        if canonical in covered:
            raise ValueError("Duplicate checksum entry")
        covered.add(canonical)
        if sha256(path) != digest:
            raise ValueError(f"Checksum mismatch: {name}")
    expected = {p.resolve() for p in root.rglob("*") if p.is_file() and p != root / "SHA256SUMS"}
    if covered != expected:
        raise ValueError("Checksum list does not cover the complete payload")


def prepare(root, output):
    verify_checksums(root)
    image = verify_image(root / "firmware", root / "image-metadata.json")
    manifest = json.loads((root / "build-manifest.json").read_text(encoding="utf-8"))
    if manifest.get("build_type") != "release" or not re.fullmatch(r"[a-f0-9]{64}", manifest.get("fingerprint", "")):
        raise ValueError("Invalid release manifest")
    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        raise ValueError("Release staging directory must be empty")
    # OpenWrt has already installed the selected packages in the FIT rootfs.
    # Renaming must preserve the validated image bytes, including fwtool metadata.
    revision = firmware_revision(root).split("-", 1)[0]
    shutil.copy2(image, output / f"{IMAGE_PREFIX}{revision}.itb")
    return manifest


def gh(*args):
    try:
        return subprocess.check_output(["gh", *args], text=True, stderr=subprocess.PIPE, timeout=180)
    except subprocess.CalledProcessError as error:
        if error.stderr:
            print(error.stderr, file=sys.stderr, end="")
        raise


def matching_asset(asset, path, digest):
    return (asset.get("state") == "uploaded" and asset.get("size") == path.stat().st_size
            and asset.get("digest") == digest)


def upload_asset(repo, endpoint, path, asset, digest):
    """Retry transient uploads without duplicating or trusting partial assets."""
    for attempt in range(3):
        if attempt:
            # A failed response can leave either a complete asset or a starter.
            # Reconcile by release ID before retrying the non-idempotent POST.
            items = json.loads(gh("api", f"{endpoint}/assets?per_page=100"))
            asset = next((item for item in items if item["name"] == path.name), {})
        if matching_asset(asset, path, digest):
            return asset
        if asset:
            gh("api", "--method", "DELETE", f"repos/{repo}/releases/assets/{asset['id']}")
        try:
            return json.loads(gh("api", "--method", "POST",
                                 f"https://uploads.github.com/{endpoint}/assets?name={quote(path.name)}",
                                 "-H", "Content-Type: application/octet-stream", "--input", str(path)))
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
            retryable = isinstance(error, subprocess.TimeoutExpired) or re.search(
                r"HTTP 5[0-9]{2}\b", error.stderr or "")
            if not retryable or attempt == 2:
                raise
            delay = 5 * 2 ** attempt
            print(f"Transient upload failure for {path.name}; retry {attempt + 2}/3 in {delay}s",
                  file=sys.stderr, flush=True)
            time.sleep(delay)


def releases(repo):
    pages = json.loads(gh("api", "--paginate", "--slurp", f"repos/{repo}/releases?per_page=100"))
    return [release for page in pages for release in page]


def managed(release):
    return bool(TAG.fullmatch(release.get("tag_name", "")) and MARKER in (release.get("body") or ""))


def complete(release):
    assets = {a["name"]: a for a in release.get("assets", []) if a.get("state") == "uploaded" and a.get("size", 0) > 0}
    single_image = (len(release.get("assets", [])) == 1 and len(assets) == 1
                    and bool(RELEASE_IMAGE.fullmatch(next(iter(assets)))))
    # Count the previous multi-asset releases during migration so retention
    # still keeps three working versions, rather than accumulating old ones.
    legacy = (all(name in assets for name in ("SHA256SUMS", "packages.tar.zst", "public-key.pem"))
              and ("build-info.tar.gz" in assets or "build-manifest.json" in assets)
              and len([name for name in assets if name.endswith("-sysupgrade.itb")]) == 1)
    return (managed(release) and not release.get("draft") and not release.get("prerelease")
            and (single_image or legacy))


def clean_drafts(repo):
    # Run before the next serialized build, never during publication retries.
    # Preserve manually created drafts and all published releases/tags.
    for item in releases(repo):
        if item.get("draft") and managed(item):
            gh("api", "--method", "DELETE", f"repos/{repo}/releases/{item['id']}")
            print(f"Deleted previous build draft: {item['tag_name']}")


def already_published(items, fingerprint):
    marker = f"<!-- fingerprint:{fingerprint} -->"
    return any(complete(item) and marker in item["body"] for item in items)


def prune_candidates(items, keep=3):
    # Never remove drafts, unrelated tags, or an older working image before a
    # new release is complete. The workflow serializes publication across hosts.
    items = sorted((item for item in items if complete(item)),
                   key=lambda item: (item.get("published_at") or "", item["id"]), reverse=True)
    return items[keep:]


def release_notes(root, manifest, repo, run_id):
    revision = firmware_revision(root)
    built_at = datetime.fromisoformat(manifest["built_at"])
    if built_at.tzinfo is None:
        raise ValueError("Build timestamp must include a timezone")
    date = built_at.astimezone(timezone(timedelta(hours=9))).strftime("%Y.%m.%d")
    title = f"ubi2-oc_{date}_{revision}"
    changes = "\n".join("    " + line for line in manifest["changelog"])
    notes = (
        f"## {title}\n\n{changes}\n\n"
        f"{MARKER}\n<!-- fingerprint:{manifest['fingerprint']} -->\n"
    )
    return title, notes


def publish(root, output, repo, run_id, attempt, commit):
    if not re.fullmatch(r"[0-9]+", run_id) or not re.fullmatch(r"[0-9]+", attempt):
        raise ValueError("Invalid workflow run identity")
    if not re.fullmatch(r"[a-f0-9]{40}", commit):
        raise ValueError("Artifact must identify an exact builder commit")
    manifest = prepare(root, output)
    if manifest.get("builder_commit") != commit:
        raise ValueError("Artifact was produced by a different builder commit")
    tag = f"{PREFIX}{run_id}-{attempt}"
    notes = output.parent / "release-notes.md"
    title, body = release_notes(root, manifest, repo, run_id)
    notes.write_text(body, encoding="utf-8")
    existing = next((item for item in releases(repo) if item["tag_name"] == tag), None)
    if existing and (not managed(existing) or f"<!-- fingerprint:{manifest['fingerprint']} -->" not in existing["body"]):
        raise ValueError("Refusing to modify a release with a different identity")
    if not existing:
        # GITHUB_TOKEN cannot tag a historical commit whose workflow files
        # differ from main (403). A release tag follows main at publication;
        # the checked manifest and notes retain the exact artifact builder SHA.
        # Use the creation response: release lists may briefly omit new drafts.
        existing = json.loads(gh("api", "--method", "POST", f"repos/{repo}/releases",
                                 "-f", f"tag_name={tag}", "-f", "target_commitish=main",
                                 "-F", "draft=true", "-F", "prerelease=false",
                                 "-f", f"name={title}", "-F", f"body=@{notes}"))
    # Drafts have an ID before their Git tag exists. Use that ID for all writes.
    endpoint = f"repos/{repo}/releases/{existing['id']}"
    actual = {a["name"]: a for a in existing.get("assets", [])}
    expected_names = {path.name for path in output.iterdir()}
    if any(name not in expected_names for name in actual):
        raise ValueError("Release contains unexpected assets; refusing to publish")
    for path in sorted(output.iterdir()):
        asset = actual.get(path.name, {})
        digest = f"sha256:{sha256(path)}"
        if existing["draft"]:
            asset = upload_asset(repo, endpoint, path, asset, digest)
        if asset.get("state") != "uploaded" or asset.get("size") != path.stat().st_size:
            raise RuntimeError(f"Release asset upload incomplete: {path.name}")
        if asset.get("digest") != digest:
            raise RuntimeError(f"Release asset digest mismatch: {path.name}")
    current = existing
    if existing["draft"]:
        current = json.loads(gh("api", "--method", "PATCH", endpoint, "-F", "draft=false", "-F", "prerelease=false",
                                "-f", "target_commitish=main", "-f", "make_latest=true", "-f", f"name={title}", "-F", f"body=@{notes}"))
    if current["tag_name"] != tag or not complete(current):
        raise RuntimeError("Published release could not be verified; retaining all previous releases")
    # The mutation response is authoritative even if the list is still stale.
    items = [item for item in releases(repo) if item["id"] != current["id"]] + [current]
    for old in prune_candidates(items):
        gh("release", "delete", old["tag_name"], "--repo", repo, "--cleanup-tag", "--yes")
    print(f"https://github.com/{repo}/releases/tag/{tag}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    verify = sub.add_parser("verify-image")
    verify.add_argument("target", type=Path)
    verify.add_argument("metadata", type=Path)
    check = sub.add_parser("check")
    check.add_argument("fingerprint")
    sub.add_parser("clean-drafts")
    upload = sub.add_parser("publish")
    upload.add_argument("artifact", type=Path)
    upload.add_argument("output", type=Path)
    args = parser.parse_args()
    if args.command == "verify-image":
        print(verify_image(args.target, args.metadata))
    elif args.command == "clean-drafts":
        clean_drafts(os.environ["GH_REPO"])
    elif args.command == "check":
        if not re.fullmatch(r"[a-f0-9]{64}", args.fingerprint):
            raise ValueError("Invalid fingerprint")
        print("build=false" if already_published(releases(os.environ["GH_REPO"]), args.fingerprint) else "build=true")
    else:
        publish(args.artifact, args.output, os.environ["GH_REPO"], os.environ["GITHUB_RUN_ID"],
                os.environ.get("RELEASE_ATTEMPT", os.environ["GITHUB_RUN_ATTEMPT"]), os.environ["GITHUB_SHA"])


if __name__ == "__main__":
    main()
