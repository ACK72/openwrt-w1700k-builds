#!/usr/bin/env python3
"""Resolve this installation's repositories from Actions or its Git remote."""
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def builder_repository():
    repo = os.environ.get("GH_REPO") or os.environ.get("GITHUB_REPOSITORY")
    if not repo:
        remote = subprocess.check_output(
            ["git", "-c", "safe.directory=" + str(ROOT), "-C", str(ROOT), "remote", "get-url", "origin"],
            text=True).strip()
        match = re.fullmatch(r"(?:https://github[.]com/|git@github[.]com:)([^/]+/[^/]+?)(?:[.]git)?", remote)
        if not match:
            raise ValueError("Set GITHUB_REPOSITORY to the firmware release repository")
        repo = match[1]
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
        raise ValueError("Invalid GitHub repository")
    return repo


def repository_url(name):
    owner = builder_repository().split("/", 1)[0]
    return f"https://github.com/{owner}/{name}.git"


if __name__ == "__main__":
    target = sys.argv[1]
    print("https://github.com/" + builder_repository() if target == "builder" else repository_url(target))
