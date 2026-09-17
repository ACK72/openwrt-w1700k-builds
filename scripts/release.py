#!/usr/bin/env python3
"""Validate W1700K images, publish complete releases, then retain the newest three."""
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

PREFIX = "w1700k-ubi2-oc-"
TAG = re.compile(r"w1700k-ubi2-oc-[0-9]+-[0-9]+\Z")
DEVICE = "gemtek_w1700k-ubi"
SUPPORTED_DEVICE = "gemtek,w1700k-ubi"
TARGET = "airoha/an7581"
MARKER = "<!-- w1700k-release:v1 -->"


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
    for path in (image, root / "build-manifest.json", root / "openwrt.config",
                 root / "config.diff", root / "feeds.lock", root / "packages.tar.zst",
                 root / "public-key.pem", root / "image-metadata.json", root / "firmware/profiles.json"):
        if path.is_symlink() or not path.is_file() or not path.stat().st_size:
            raise ValueError(f"Missing/invalid release asset: {path.name}")
        shutil.copy2(path, output / path.name)
    (output / "SHA256SUMS").write_text("".join(
        f"{sha256(p)}  {p.name}\n" for p in sorted(output.iterdir())), encoding="utf-8")
    return manifest


def gh(*args):
    return subprocess.check_output(["gh", *args], text=True)


def releases(repo):
    pages = json.loads(gh("api", "--paginate", "--slurp", f"repos/{repo}/releases?per_page=100"))
    return [release for page in pages for release in page]


def managed(release):
    return bool(TAG.fullmatch(release.get("tag_name", "")) and MARKER in (release.get("body") or ""))


def complete(release):
    assets = {a["name"]: a for a in release.get("assets", []) if a.get("state") == "uploaded" and a.get("size", 0) > 0}
    return (managed(release) and not release.get("draft") and not release.get("prerelease")
            and all(name in assets for name in ("SHA256SUMS", "build-manifest.json", "packages.tar.zst", "public-key.pem"))
            and len([name for name in assets if name.endswith("-sysupgrade.itb")]) == 1)


def already_published(items, fingerprint):
    marker = f"<!-- fingerprint:{fingerprint} -->"
    return any(complete(item) and marker in item["body"] for item in items)


def prune_candidates(items, keep=3):
    # Never remove drafts, unrelated tags, or an older working image before a
    # new release is complete. The workflow serializes publication across hosts.
    items = sorted((item for item in items if complete(item)),
                   key=lambda item: (item.get("published_at") or "", item["id"]), reverse=True)
    return items[keep:]


def publish(root, output, repo, run_id, attempt, commit):
    if not re.fullmatch(r"[0-9]+", run_id) or not re.fullmatch(r"[0-9]+", attempt):
        raise ValueError("Invalid workflow run identity")
    if not re.fullmatch(r"[a-f0-9]{40}", commit):
        raise ValueError("Release must point at an exact builder commit")
    manifest = prepare(root, output)
    if manifest.get("builder_commit") != commit:
        raise ValueError("Artifact was produced by a different builder commit")
    tag = f"{PREFIX}{run_id}-{attempt}"
    notes = output.parent / "release-notes.md"
    notes.write_text(
        f"{MARKER}\n<!-- fingerprint:{manifest['fingerprint']} -->\n\n"
        "Gemtek W1700K UBI2-OC 릴리즈입니다. 설치 파일은 `*-sysupgrade.itb`입니다.\n\n"
        "현재 UBI2 파티션 구성을 사용하는 기기에서만 설치하세요. 순정 펌웨어에서 직접 설치하거나 "
        "다른 파티션 구성에 강제 설치하는 용도가 아닙니다.\n\n"
        f"- OpenWrt: `{manifest['openwrt']}`\n- NPU FDK: `{manifest['npu']}`\n"
        f"- Builder: `{commit}`\n- 실행: https://github.com/{repo}/actions/runs/{run_id}\n\n"
        "다운로드 후 `sha256sum -c SHA256SUMS --ignore-missing`으로 확인하세요. "
        "`packages.tar.zst`는 이 이미지와 함께 빌드한 APK 묶음입니다. "
        "다른 빌드의 kmod를 혼용하지 마세요.\n\n"
        "`openwrt.config`, `feeds.lock`, `build-manifest.json`에 빌드 입력을 기록했습니다. "
        "이 릴리즈는 ubi2-oc 포크 기반이며 OpenWrt 공식 stable 릴리즈가 아닙니다. "
        "CI는 이미지 무결성과 기기 메타데이터를 검증하며 실제 기기 부팅 검증을 대신하지 않습니다.\n",
        encoding="utf-8")
    existing = next((item for item in releases(repo) if item["tag_name"] == tag), None)
    if existing and (not managed(existing) or f"<!-- fingerprint:{manifest['fingerprint']} -->" not in existing["body"]):
        raise ValueError("Refusing to modify a release with a different identity")
    if not existing:
        gh("release", "create", tag, "--repo", repo, "--draft", "--target", commit,
           "--title", f"W1700K UBI2-OC {run_id}.{attempt}", "--notes-file", str(notes))
    if not existing or existing["draft"]:
        gh("release", "upload", tag, *[str(p) for p in sorted(output.iterdir())], "--repo", repo, "--clobber")
    current = json.loads(gh("api", f"repos/{repo}/releases/tags/{tag}"))
    actual = {a["name"]: a for a in current.get("assets", [])}
    for path in output.iterdir():
        asset = actual.get(path.name, {})
        if asset.get("state") != "uploaded" or asset.get("size") != path.stat().st_size:
            raise RuntimeError(f"Release asset upload incomplete: {path.name}")
        if asset.get("digest") != f"sha256:{sha256(path)}":
            raise RuntimeError(f"Release asset digest mismatch: {path.name}")
    if current["draft"]:
        gh("release", "edit", tag, "--repo", repo, "--draft=false", "--prerelease=false", "--latest")
    items = releases(repo)
    if not any(item["tag_name"] == tag and complete(item) for item in items):
        raise RuntimeError("Published release could not be verified; retaining all previous releases")
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
    upload = sub.add_parser("publish")
    upload.add_argument("artifact", type=Path)
    upload.add_argument("output", type=Path)
    args = parser.parse_args()
    if args.command == "verify-image":
        print(verify_image(args.target, args.metadata))
    elif args.command == "check":
        if not re.fullmatch(r"[a-f0-9]{64}", args.fingerprint):
            raise ValueError("Invalid fingerprint")
        print("build=false" if already_published(releases(os.environ["GH_REPO"]), args.fingerprint) else "build=true")
    else:
        publish(args.artifact, args.output, os.environ["GH_REPO"], os.environ["GITHUB_RUN_ID"],
                os.environ.get("RELEASE_ATTEMPT", os.environ["GITHUB_RUN_ATTEMPT"]), os.environ["GITHUB_SHA"])


if __name__ == "__main__":
    main()
