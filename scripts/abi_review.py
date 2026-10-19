#!/usr/bin/env python3
"""Stop the source stack when it changes the kernel ABI without a review.

The firmware carries the official snapshot's vermagic, so kmods from the
official feeds install on it. That is only safe while the kernel keeps the
official ABI. Every stack kernel patch whose include/ changes differ from the
official tree, every kernel config difference and the profile's kernel options
therefore need an entry in patches/abi-review.json.
"""
import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "patches/abi-review.json"
PROFILE = ROOT / "configs/w1700k.config"
TARGET, SUBTARGET = "airoha", "an7581"


def git(repo, *args):
    return subprocess.check_output(["git", "-C", str(repo), *args], encoding="utf-8")


def show(repo, rev, path):
    result = subprocess.run(["git", "-C", str(repo), "show", f"{rev}:{path}"],
                            capture_output=True, encoding="utf-8", errors="replace")
    return result.stdout if result.returncode == 0 else None


def digest(text):
    return hashlib.sha256(text.encode()).hexdigest()


def kernel_version(repo, rev):
    match = re.search(r"^KERNEL_PATCHVER\s*:?=\s*(\S+)", show(repo, rev, f"target/linux/{TARGET}/Makefile") or "", re.M)
    if not match:
        raise ValueError("KERNEL_PATCHVER is missing from the target Makefile")
    return match[1]


def header_changes(text):
    """Changed include/ lines of a patch, without offsets or context."""
    lines, out, i = text.splitlines(), [], 0
    while i < len(lines):
        if not (lines[i].startswith("--- ") and i + 1 < len(lines) and lines[i + 1].startswith("+++ ")):
            i += 1
            continue
        old, new = (line[4:].split("\t")[0].strip() for line in lines[i:i + 2])
        name = new if new != "/dev/null" else old
        path = name.split("/", 1)[1] if "/" in name else name
        i += 2
        while i < len(lines):
            hunk = re.match(r"@@ -\d+(?:,(\d+))? \+\d+(?:,(\d+))? @@", lines[i])
            if not hunk:
                break
            old_left = int(hunk[1] if hunk[1] is not None else 1)
            new_left = int(hunk[2] if hunk[2] is not None else 1)
            i += 1
            while (old_left > 0 or new_left > 0) and i < len(lines):
                line = lines[i]
                i += 1
                if line.startswith("\\"):
                    continue
                if line.startswith("-"):
                    old_left -= 1
                elif line.startswith("+"):
                    new_left -= 1
                else:
                    old_left -= 1
                    new_left -= 1
                    continue
                if path.startswith("include/"):
                    out.append(f"{path}\0{line}")
    return "\n".join(out)


def stack_changes(repo, official, head):
    """Header and kernel config differences between the official tree and the stack."""
    version = kernel_version(repo, head)
    dirs = [f"target/linux/generic/{kind}-{version}" for kind in ("backport", "pending", "hack")]
    dirs.append(f"target/linux/{TARGET}/patches-{version}")
    changes = []
    for path in git(repo, "diff", "--name-only", "--no-renames", official, head, "--", *dirs).split():
        before, after = (show(repo, rev, path) for rev in (official, head))
        old, new = (header_changes(text) if text else "" for text in (before, after))
        if old != new:
            kind = "added" if before is None else "removed" if after is None else "modified"
            changes.append({"kind": "header", "patch": path, "change": kind,
                            "fingerprint": digest(f"{old}\0\0{new}"), "lines": (new or old).splitlines()})
    files = [f"target/linux/generic/files-{version}", "target/linux/generic/files",
             f"target/linux/{TARGET}/files-{version}", f"target/linux/{TARGET}/files"]
    for path in git(repo, "diff", "--name-only", official, head, "--", *files).split():
        if "/include/" in path:
            text = git(repo, "diff", official, head, "--", path)
            changes.append({"kind": "header", "patch": path, "change": "file",
                            "fingerprint": digest(text), "lines": text.splitlines()[:40]})
    configs = [f"target/linux/generic/config-{version}", f"target/linux/{TARGET}/config-{version}",
               f"target/linux/{TARGET}/{SUBTARGET}/config-{version}"]
    text = git(repo, "diff", "-U0", official, head, "--", *configs)
    lines = [line for line in text.splitlines() if line[:1] in "+-" and not line.startswith(("+++", "---"))]
    if lines:
        changes.append({"kind": "config", "patch": ", ".join(configs), "change": "config",
                        "fingerprint": digest("\n".join(lines)), "lines": lines})
    options = sorted(line for line in PROFILE.read_text(encoding="utf-8").splitlines()
                     if re.match(r"(# )?CONFIG_KERNEL_", line))
    if options:
        changes.append({"kind": "profile", "patch": str(PROFILE.relative_to(ROOT)).replace("\\", "/"),
                        "change": "kernel options", "fingerprint": digest("\n".join(options)), "lines": options})
    return changes, dirs


def check(repo, official, head="HEAD", manifest=MANIFEST):
    review = json.loads(Path(manifest).read_text(encoding="utf-8"))
    reviewed = {entry["fingerprint"]: entry for entry in review["reviewed"]}
    changes, dirs = stack_changes(repo, official, head)
    problems = []
    for change in changes:
        if change["fingerprint"] not in reviewed:
            problems.append(change)
    for guard in review.get("official_must_not_contain", []):
        hits = subprocess.run(["git", "-C", str(repo), "grep", "-l", "-F", "-e", guard["text"], official, "--", *dirs],
                              capture_output=True, encoding="utf-8").stdout.split()
        if hits:
            problems.append({"kind": "guard", "patch": ", ".join(hit.split(":", 1)[1] for hit in hits),
                             "change": guard["reason"], "fingerprint": "", "lines": [guard["text"]]})
    seen = {change["fingerprint"] for change in changes}
    for entry in review["reviewed"]:
        if entry["fingerprint"] not in seen:
            print(f"Reviewed ABI entry no longer present (prune it): {entry['patch']}")
    if problems:
        for problem in problems:
            print(f"Unreviewed kernel ABI change: {problem['patch']} ({problem['change']})")
            for line in problem["lines"][:12]:
                print("    " + line.replace("\0", ": "))
            if problem["fingerprint"]:
                print("  Add after review: " + json.dumps({"patch": problem["patch"], "change": problem["change"],
                                                         "fingerprint": problem["fingerprint"],
                                                         "verdict": "", "reason": ""}))
        raise SystemExit("Review the kernel ABI changes above in patches/abi-review.json; see docs/kmod-compatibility.md")
    print(f"Kernel ABI review: {len(changes)} reviewed differences from the official tree")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo", type=Path, help="composed source repository")
    parser.add_argument("official", help="official OpenWrt revision the stack is based on")
    parser.add_argument("--head", default="HEAD")
    args = parser.parse_args()
    check(args.repo, args.official, args.head)


if __name__ == "__main__":
    main()
