"""Validate the APK install list against the final firmware manifest."""
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
spec = importlib.util.spec_from_file_location("build_meta_packages", ROOT / "scripts/build-meta.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class InstalledPackages(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        (self.root / "tmp").mkdir()
        self.target = self.root / "bin/targets/airoha/an7581"
        self.target.mkdir(parents=True)
        self.inventory = self.root / "tmp/apk_install_list"
        self.manifest = self.target / "firmware.manifest"

    def write_inventory(self, requested, installed):
        self.inventory.write_text(requested, encoding="utf-8")
        self.manifest.write_text(installed, encoding="utf-8")

    def test_plain_names_and_abi_suffixed_libraries(self):
        self.write_inventory("base-files libc libubox20250818",
                             "base-files - 1707~3f0b4b28be\nlibc - 1.2.6-r5\n"
                             "libubox20250818 - 2025.08.18-r1\nextra - 1-r1\n")
        module.check_installed(self.root)

    def test_upstream_version_pins(self):
        kernel = "6.18.52~8a2128798a21753379be49e778752d44-r1"
        self.write_inventory(f"base-files=1707~3f0b4b28be\nlibc=1.2.6-r5 kernel={kernel} busybox",
                             f"base-files - 1707~3f0b4b28be\nlibc - 1.2.6-r5\n"
                             f"kernel - {kernel}\nbusybox - 1.37.0-r1\n")
        module.check_installed(self.root)

    def test_missing_plain_and_pinned_packages_fail(self):
        for requirement in ("libc", "libc=1.2.6-r5"):
            with self.subTest(requirement=requirement):
                self.write_inventory(requirement, "libcap - 2.77-r1\n")
                with self.assertRaisesRegex(RuntimeError, "Packages missing from image rootfs: " + requirement):
                    module.check_installed(self.root)

    def test_wrong_pinned_version_fails(self):
        self.write_inventory("libc=1.2.6-r5", "libc - 1.2.6-r4\n")
        with self.assertRaisesRegex(RuntimeError, r"Package versions differ.*libc=1.2.6-r5.*installed 1.2.6-r4"):
            module.check_installed(self.root)

    def test_unsupported_requirements_fail_closed(self):
        for requirement in ("libc>=1.2.6-r5", "libc=", "libc==1.2.6-r5", "!libc"):
            with self.subTest(requirement=requirement):
                self.write_inventory(requirement, "libc - 1.2.6-r5\n")
                with self.assertRaisesRegex(RuntimeError, "Unsupported image package requirement"):
                    module.check_installed(self.root)

    def test_missing_or_ambiguous_inventory_fails(self):
        self.write_inventory("", "libc - 1.2.6-r5\n")
        with self.assertRaisesRegex(RuntimeError, "Missing or ambiguous"):
            module.check_installed(self.root)
        self.inventory.write_text("libc", encoding="utf-8")
        self.manifest.unlink()
        with self.assertRaisesRegex(RuntimeError, "Missing or ambiguous"):
            module.check_installed(self.root)
        self.manifest.write_text("libc - 1.2.6-r5\n", encoding="utf-8")
        (self.target / "second.manifest").write_text("libc - 1.2.6-r5\n", encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError, "Missing or ambiguous"):
            module.check_installed(self.root)
