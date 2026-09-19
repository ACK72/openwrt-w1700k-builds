#!/usr/bin/env python3
"""Content-based cache keys, strict firmware integration, and build provenance."""
import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import tarfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLCHAIN_INPUTS = (
    "tools", "toolchain", "include", "scripts", "Makefile", "rules.mk",
    "target/Config.in", "target/Makefile", "target/linux/Makefile",
    "target/linux/airoha/Makefile", "target/linux/airoha/an7581/target.mk",
)
KERNEL_INPUTS = ("target/linux/airoha", "target/linux/generic", "package/kernel/linux")
PACKAGE = "airoha-en7581-mt7996-npu-firmware"
BINARIES = ("en7581_MT7996_npu_rv32.bin", "en7581_MT7996_npu_data.bin")
REQUIRED_CONFIG = (
    "CONFIG_TARGET_airoha_an7581_DEVICE_gemtek_w1700k-ubi",
    "CONFIG_PACKAGE_airoha-en7581-mt7996-npu-firmware",
    "CONFIG_PACKAGE_kmod-mt7996e", "CONFIG_CCACHE",
)


def git(path, *args):
    # Checkout runs as the runner user; the build container runs as root.
    # Trust only the exact managed repository for this command, never all paths.
    return subprocess.check_output(["git", "-c", f"safe.directory={path.resolve()}",
                                    "-C", str(path), *args], text=True).strip()


def builder_commit():
    try:
        commit = git(ROOT, "rev-parse", "--verify", "HEAD")
    except subprocess.CalledProcessError:
        if os.environ.get("GITHUB_ACTIONS") == "true":
            raise RuntimeError("Cannot verify the CI builder checkout") from None
        return "uncommitted (see builder content hash)"
    if os.environ.get("GITHUB_ACTIONS") == "true" and commit != os.environ.get("GITHUB_SHA"):
        raise ValueError("Builder checkout does not match the workflow commit")
    return commit


def digest_paths(root, names):
    digest = hashlib.sha256()
    for name in sorted(names):
        base = root / name
        paths = sorted(base.rglob("*")) if base.is_dir() and not base.is_symlink() else [base]
        for path in paths:
            if (path.is_dir() and not path.is_symlink()) or "__pycache__" in path.parts:
                continue
            digest.update(path.relative_to(root).as_posix().encode() + b"\0")
            digest.update((path.lstat().st_mode & 0o777).to_bytes(2, "big"))
            if path.is_symlink():
                digest.update(b"link\0" + os.readlink(path).encode())
            else:
                digest.update(b"file\0" + path.read_bytes())
            digest.update(b"\0")
    return digest.hexdigest()


def read_config(path):
    values = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        disabled = re.fullmatch(r"# (CONFIG_\S+) is not set", line)
        if disabled:
            values[disabled[1]] = "n"
        elif line.startswith("CONFIG_") and "=" in line:
            name, value = line.split("=", 1)
            values[name] = value
    return values


def config_digest(path, toolchain=False, symbols=None):
    """Package selection and release labels do not change compiler binaries."""
    values = read_config(path)
    ignored = ("CONFIG_VERSION_", "CONFIG_PACKAGE_") if toolchain and symbols is None else ("CONFIG_VERSION_",)
    # Feeds frequently add unselected packages. An absent boolean and an
    # explicitly disabled boolean are equivalent after make defconfig.
    values = {key: value for key, value in values.items()
              if value != "n" and not key.startswith(ignored)}
    if toolchain:
        # Kernel runtime options and userspace configuration do not change the
        # compiler. Kernel source selection still changes exported libc headers.
        values = {key: value for key, value in values.items()
                  if not key.startswith(("CONFIG_BUSYBOX_", "CONFIG_DEFAULT_"))
                  and (not key.startswith("CONFIG_KERNEL_") or key.startswith("CONFIG_KERNEL_GIT_"))
                  and (symbols is None or key in symbols)}
    return hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest()


def toolchain_inputs(openwrt):
    tracked = git(openwrt, "ls-files", "--", *TOOLCHAIN_INPUTS,
                  "target/linux/generic/kernel-*").splitlines()
    # kernel-headers overrides PATCH_DIR with toolchain/kernel-headers/patches.
    # Runtime target patches are not applied to the toolchain's exported headers.
    target = (openwrt / "target/linux/airoha/Makefile").read_text()
    versions = re.findall(r"^KERNEL_(?:TESTING_)?PATCHVER\s*:?=\s*(\S+)", target, re.M)
    tracked = [name for name in tracked if not name.startswith("target/linux/generic/kernel-")
               or name.rsplit("kernel-", 1)[1] in versions]
    return tracked


def kernel_inputs(openwrt):
    tracked = git(openwrt, "ls-files", "--", *KERNEL_INPUTS).splitlines()
    versions = {name.rsplit("kernel-", 1)[1] for name in toolchain_inputs(openwrt)
                if name.startswith("target/linux/generic/kernel-")}
    return [name for name in tracked if not (match := re.search(
        r"/(?:backport|pending|hack|patches|files|config|kernel)-(\d+\.\d+)(?:/|$)", name))
        or match[1] in versions]


def toolchain_symbols(openwrt, tracked):
    symbols = set()
    for name in tracked:
        path = openwrt / name
        if path.is_symlink() or path.suffix in (".patch", ".gz", ".xz"):
            continue
        text = path.read_text(errors="replace")
        symbols.update(re.findall(r"\bCONFIG_[A-Za-z0-9_]+", text))
        symbols.update("CONFIG_" + item for item in re.findall(
            r"^\s*(?:menuconfig|config)\s+([A-Za-z0-9_]+)", text, re.M))
    # Computed Make variable names and generated target identities.
    symbols.update(key for key in read_config(openwrt / ".config")
                   if key.startswith(("CONFIG_TARGET_", "CONFIG_GCC_", "CONFIG_BINUTILS_",
                                      "CONFIG_LIBC_", "CONFIG_MUSL_", "CONFIG_TOOLCHAIN_",
                                      "CONFIG_KERNEL_GIT_")))
    return symbols


def target_packages(openwrt):
    """Keep target/device defaults when registering only selected feed recipes."""
    metadata = (openwrt / "tmp/.targetinfo").read_text(encoding="utf-8")
    targets = re.split(r"(?m)^Target: ", metadata)
    target = next((item for item in targets if item.startswith("airoha/an7581\n")), "")
    profiles = re.split(r"(?m)^Target-Profile: ", target)
    device = next((item for item in profiles if item.startswith("DEVICE_gemtek_w1700k-ubi\n")), "")
    defaults = re.search(r"(?m)^Default-Packages: (.*)$", profiles[0])
    packages = re.search(r"(?m)^Target-Profile-Packages: (.*)$", device)
    if not defaults or not packages:
        raise RuntimeError("W1700K target/device package metadata is missing")
    names = (defaults[1] + " " + packages[1]).split()
    return {name for name in names if not name.startswith("-")} - {
        name[1:] for name in names if name.startswith("-")
    }


def requested_packages(openwrt, profile):
    expected = {"CONFIG_PACKAGE_" + name: "y" for name in target_packages(openwrt)}
    expected.update(read_config(profile))
    return expected


def feed_packages(openwrt, profile):
    requested = requested_packages(openwrt, profile)
    packages = {name.removeprefix("CONFIG_PACKAGE_")
                for name, value in requested.items()
                if name.startswith("CONFIG_PACKAGE_") and value in ("y", "m")}
    if requested.get("CONFIG_ALL_KMODS") == "y":
        # ALL_KMODS can only select registered recipes. Include feed modules
        # too, without importing unrelated userspace recipes with Kconfig cycles.
        for index in (openwrt / "feeds").glob("*.index"):
            packages.update(re.findall(r"(?m)^Package: (kmod-\S+)$", index.read_text(encoding="utf-8")))
    return sorted(packages)


def check_config(openwrt, profile):
    actual = read_config(openwrt / ".config")
    # Defaults are feed installation roots, not exact Kconfig requirements:
    # virtual packages and TLS alternatives may resolve to another provider.
    expected = read_config(profile)
    expected.update(dict.fromkeys(REQUIRED_CONFIG, "y"))
    mismatches = [
        f"{name}: requested {value}, got {actual.get(name, 'n')}"
        for name, value in expected.items()
        if actual.get(name, "n") != value
    ]
    if mismatches:
        raise RuntimeError("Configuration lost after defconfig:\n" + "\n".join(mismatches))


def check_installed(openwrt):
    """Verify APK's actual rootfs inventory, including ABI-suffixed libraries."""
    requested = set((openwrt / "tmp/apk_install_list").read_text().split())
    manifests = list((openwrt / "bin/targets/airoha/an7581").glob("*.manifest"))
    if not requested or len(manifests) != 1:
        raise RuntimeError("Missing or ambiguous image package inventory")
    installed = {line.split(" - ", 1)[0] for line in manifests[0].read_text().splitlines() if " - " in line}
    missing = requested - installed
    if missing:
        raise RuntimeError("Packages missing from image rootfs: " + ", ".join(sorted(missing)))
    print(f"Verified {len(requested)} requested packages in the image rootfs ({len(installed)} installed)")


def install_npu(openwrt, npu, firmware):
    # Replace just the MT7996 definition, leaving MT7992/AN7583 packages intact.
    # Fail closed if the upstream recipe changes instead of building vendor blobs.
    recipe = openwrt / "package/firmware/linux-firmware/airoha.mk"
    text = recipe.read_text()
    marker = "# MT7996 firmware is provided by package/firmware/airoha-npu-fdk."
    pattern = (
        rf"Package/{PACKAGE} = [^\n]+\n"
        rf"define Package/{PACKAGE}/install\n.*?\nendef\n\n"
        rf"\$\(eval \$\(call BuildPackage,{PACKAGE}\)\)"
    )
    if marker not in text:
        text, count = re.subn(pattern, marker, text, flags=re.S)
        if count != 1:
            raise RuntimeError("MT7996 linux-firmware recipe changed; review integration")
    if f"BuildPackage,{PACKAGE}" in text or f"Package/{PACKAGE}" in text:
        raise RuntimeError("MT7996 linux-firmware recipe changed; duplicate definition")
    for name in BINARIES:
        if not (firmware / name).is_file() or not (firmware / name).stat().st_size:
            raise RuntimeError(f"Missing/empty FDK output: {name}")
    # OpenWrt disables compression by default. Cache capacity is constrained in
    # Actions, so keep ccache's fast zstd compression in this managed checkout.
    rules = openwrt / "rules.mk"
    rules_text = rules.read_text()
    rules_text = rules_text.replace(
        "export CCACHE_NOCOMPRESS:=true", "export CCACHE_COMPRESS:=true"
    )
    package = openwrt / "package/firmware/airoha-npu-fdk"
    (package / "files").mkdir(parents=True, exist_ok=True)
    revision = git(npu, "rev-parse", "HEAD")
    template = (ROOT / "package/airoha-npu-fdk/Makefile").read_text()
    (package / "Makefile").write_text(template.replace("@NPU_VERSION@", "0~" + revision[:12]))
    for name in BINARIES:
        shutil.copy2(firmware / name, package / "files" / name)
    shutil.copy2(npu / "LICENSE", package / "files/LICENSE")
    recipe.write_text(text)
    rules.write_text(rules_text)


def keys(openwrt, npu):
    commit = builder_commit()
    feeds = {
        p.name: git(p, "rev-parse", "HEAD")
        for p in sorted((openwrt / "feeds").iterdir())
        if p.is_dir() and not p.is_symlink() and (p / ".git").exists()
    }
    # A browser/SDK update in the runner image is unrelated to the compiler.
    # Include the build dependencies and their installed dependency closure.
    host = subprocess.check_output(
        ["bash", str(ROOT / "scripts/host-key.sh")], text=True
    )
    # Use tracked inputs only: generated conf binaries and pycache must not
    # invalidate a toolchain cache after make defconfig.
    tracked = toolchain_inputs(openwrt)
    source_hash = digest_paths(openwrt, tracked)
    builder_hash = digest_paths(ROOT, ["scripts", "configs", "package", "patches", ".github", "LICENSES", "containers"])
    host_hash = hashlib.sha256((platform.machine() + host).encode()).hexdigest()
    tool_config = config_digest(openwrt / ".config", True, toolchain_symbols(openwrt, tracked))
    toolchain = hashlib.sha256(
        ("toolchain-v3" + source_hash + host_hash + tool_config).encode()
    ).hexdigest()
    # Feed-list changes require a new image, but only a changed kernel identity
    # invalidates kernel/package products. Both keep the compiler/toolchain cache.
    vermagic = (openwrt / "files/etc/vermagic.txt").read_text().strip()
    if not re.fullmatch(r"[a-f0-9]{32}", vermagic):
        raise ValueError("Missing or invalid official kernel vermagic")
    distfeeds = digest_paths(openwrt, ["files/etc/vermagic.txt", "files/etc/apk/repositories.d/distfeeds.list"])
    bootstrap_root = read_config(openwrt / ".config").get("CONFIG_GOLANG_EXTERNAL_BOOTSTRAP_ROOT", '""').strip('"')
    # Host Go changes invalidate package products, not the C/C++ cross-toolchain.
    bootstrap = digest_paths(Path(bootstrap_root), ["bin", "pkg", "src", "VERSION"]) if bootstrap_root else ""
    base_inputs = toolchain + config_digest(openwrt / ".config") + bootstrap
    build_base = hashlib.sha256(base_inputs.encode()).hexdigest()
    kernel_hash = digest_paths(openwrt, kernel_inputs(openwrt))
    build = hashlib.sha256(("build-v3" + base_inputs + kernel_hash + vermagic).encode()).hexdigest()
    state = {
        "openwrt": git(openwrt, "rev-parse", "HEAD"),
        "npu": ("linux-firmware:" + stock_npu_info(openwrt)["version"]
                if os.environ.get("NPU_SOURCE") == "linux-firmware" else git(npu, "rev-parse", "HEAD")),
        "npu_source": os.environ.get("NPU_SOURCE", "fdk"),
        "feeds": feeds, "builder": builder_hash, "builder_commit": commit, "toolchain": toolchain,
        "host": host_hash, "build": build,
        "config": digest_paths(openwrt, [".config"]), "channel": "w1700k-oc-rc",
        "distfeeds": distfeeds, "vermagic": vermagic, "build_base": build_base,
        "toolchain_source": source_hash, "toolchain_config": tool_config,
        "kernel_source": kernel_hash, "go_bootstrap": bootstrap,
        "environment": os.environ.get("BUILD_ENVIRONMENT", "local"),
    }
    fingerprint = hashlib.sha256(json.dumps(state, sort_keys=True).encode()).hexdigest()
    state["fingerprint"] = fingerprint
    (openwrt.parent / "build-state.json").write_text(json.dumps(state, indent=2) + "\n")
    print(f"toolchain={toolchain}\nbuild={build}\nbuild-base={build_base}\nfingerprint={fingerprint}")


def manifest(openwrt, npu, output):
    state = json.loads((openwrt.parent / "build-state.json").read_text())
    state["build_type"] = "release"
    stack_file = openwrt.parent / "source-stack.json"
    state["source_stack"] = json.loads(stack_file.read_text(encoding="utf-8"))
    if state["source_stack"]["source"] != state["openwrt"]:
        raise ValueError("Build source differs from the composed RC")
    state["builder_commit"] = builder_commit()
    state["source_date_epoch"] = git(openwrt, "show", "-s", "--format=%ct", "HEAD")
    state["built_at"] = datetime.now(timezone.utc).isoformat()
    state["official_distfeeds"] = json.loads((openwrt.parent / "distfeeds.json").read_text(encoding="utf-8"))
    state["changelog"] = git(openwrt, "log", "-20", "--format=%h %s", "--abbrev=10", "HEAD").splitlines()
    stock = state.get("npu_source") == "linux-firmware"
    state["npu_compiler"] = None if stock else subprocess.check_output(["clang-18", "--version"], text=True).strip()
    state["npu_patches"] = {} if stock else {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted((ROOT / "patches/npu").glob("*.patch"))
    }
    state["firmware_sha256"] = {
        name: hashlib.sha256((output / "npu" / name).read_bytes()).hexdigest()
        for name in BINARIES
    }
    if stock:
        state["npu_upstream"] = stock_npu_info(openwrt)
        state["build_type"] = "diagnostic"
    (output / "build-manifest.json").write_text(json.dumps(state, indent=2) + "\n")


def stock_npu_info(openwrt):
    directory = openwrt / "package/firmware/linux-firmware"
    recipe = directory / "airoha.mk"
    if recipe.read_bytes() != subprocess.check_output(
            ["git", "-c", f"safe.directory={openwrt.resolve()}", "-C", str(openwrt),
             "show", "HEAD:package/firmware/linux-firmware/airoha.mk"]):
        raise ValueError("Stock NPU recipe differs from the pinned OpenWrt source")
    if (openwrt / "package/firmware/airoha-npu-fdk").exists():
        raise ValueError("FDK replacement package must not exist in a stock NPU build")
    makefile = (directory / "Makefile").read_text()
    version = re.search(r"^PKG_VERSION:=(\d+)$", makefile, re.M)
    checksum = re.search(r"^PKG_HASH:=([a-f0-9]{64})$", makefile, re.M)
    if not version or not checksum or f"BuildPackage,{PACKAGE}" not in recipe.read_text():
        raise ValueError("Unexpected upstream linux-firmware recipe")
    return {"provider": "linux-firmware", "version": version[1], "archive_sha256": checksum[1],
            "recipe_sha256": hashlib.sha256(recipe.read_bytes()).hexdigest()}


def collect_stock_npu(openwrt, output):
    info = stock_npu_info(openwrt)
    archive = openwrt / "dl" / f"linux-firmware-{info['version']}.tar.xz"
    with archive.open("rb") as stream:
        if hashlib.file_digest(stream, "sha256").hexdigest() != info["archive_sha256"]:
            raise ValueError("Original linux-firmware archive checksum mismatch")
    roots = list((openwrt / "build_dir").glob("target-*/root-airoha"))
    if len(roots) != 1:
        raise ValueError("Expected exactly one image rootfs")
    destination = output / "npu"
    destination.mkdir(parents=True, exist_ok=True)
    prefix = f"linux-firmware-{info['version']}/"
    wanted = {prefix + "airoha/" + name: name for name in BINARIES}
    wanted[prefix + "LICENSE.airoha"] = "LICENSE"
    found = set()
    # Read both paired blobs from the verified original archive in one pass.
    with tarfile.open(archive, mode="r|xz") as source:
        for member in source:
            name = wanted.get(member.name)
            if name is None:
                continue
            if not member.isfile() or not 0 < member.size < 32 * 1024 * 1024:
                raise ValueError("Invalid original firmware archive member")
            content = source.extractfile(member).read()
            if name in BINARIES:
                installed = roots[0] / "lib/firmware/airoha" / name
                if installed.read_bytes() != content:
                    raise ValueError(f"Image still contains a replaced NPU blob: {name}")
            (destination / name).write_bytes(content)
            found.add(name)
            if found == set(wanted.values()):
                break
    if found != set(wanted.values()):
        raise ValueError("Original archive is missing the paired NPU blobs or license")
    print("Verified both installed NPU blobs byte-for-byte against the original linux-firmware archive")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("check-stock-npu").add_argument("openwrt", type=Path)
    collect_parser = subparsers.add_parser("collect-stock-npu")
    collect_parser.add_argument("openwrt", type=Path)
    collect_parser.add_argument("output", type=Path)
    for command in ("install-npu", "keys", "manifest", "check-config", "feed-packages", "check-installed"):
        subparser = subparsers.add_parser(command)
        subparser.add_argument("openwrt", type=Path)
        if command in ("check-config", "feed-packages"):
            subparser.add_argument("profile", type=Path)
        elif command != "check-installed":
            subparser.add_argument("npu", type=Path)
            if command != "keys":
                subparser.add_argument("output", type=Path)
    args = parser.parse_args()
    if args.command == "check-stock-npu":
        print(json.dumps(stock_npu_info(args.openwrt), sort_keys=True))
    elif args.command == "collect-stock-npu":
        collect_stock_npu(args.openwrt, args.output)
    elif args.command == "check-config":
        check_config(args.openwrt, args.profile)
    elif args.command == "check-installed":
        check_installed(args.openwrt)
    elif args.command == "feed-packages":
        print("\n".join(feed_packages(args.openwrt, args.profile)))
    elif args.command == "keys":
        keys(args.openwrt, args.npu)
    elif args.command == "install-npu":
        install_npu(args.openwrt, args.npu, args.output)
    else:
        manifest(args.openwrt, args.npu, args.output)


if __name__ == "__main__":
    main()
