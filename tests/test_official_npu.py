"""Catch swapped/cached FDK blobs and tampered official firmware inputs."""
import hashlib
import io
import json
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from official_npu import BINARIES, PACKAGE, RECIPES, collect_stock_npu, npu_identity, stock_npu_info


class OfficialNpuTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / "openwrt"
        self.root.mkdir()
        self.output = self.base / "artifacts"
        self.blobs = {BINARIES[0]: b"official-program", BINARIES[1]: b"official-data", "LICENSE": b"Airoha terms"}
        self.write_archive(self.blobs)
        self.commit()
        self.official = self.git("rev-parse", "HEAD").strip()
        (self.base / "source-stack.json").write_text(json.dumps({"upstream": self.official}))

    def git(self, *args):
        return subprocess.check_output(["git", "-c", f"safe.directory={self.root.resolve()}",
                                        "-C", str(self.root), *args], text=True, stderr=subprocess.PIPE)

    def commit(self):
        if not (self.root / ".git").exists():
            self.git("init", "-q")
            self.git("config", "core.autocrlf", "false")
            self.git("config", "user.name", "Fixture")
            self.git("config", "user.email", "fixture@example.invalid")
        self.git("add", "package")
        self.git("commit", "-qm", "Official firmware fixture")

    def write_archive(self, blobs):
        self.archive = self.root / "dl/linux-firmware-20260910.tar.xz"
        self.archive.parent.mkdir(exist_ok=True)
        with tarfile.open(self.archive, "w:xz") as archive:
            for name, data in blobs.items():
                member = tarfile.TarInfo("linux-firmware-20260910/" + (
                    "LICENSES/LICENSE.airoha" if name == "LICENSE" else "airoha/" + name))
                member.size = len(data)
                archive.addfile(member, io.BytesIO(data))
        checksum = hashlib.sha256(self.archive.read_bytes()).hexdigest()
        makefile = self.root / RECIPES[0]
        makefile.parent.mkdir(parents=True, exist_ok=True)
        makefile.write_text(f"PKG_VERSION:=20260910\nPKG_HASH:={checksum}\n", newline="\n")
        (self.root / RECIPES[1]).write_text(f"$(eval $(call BuildPackage,{PACKAGE}))\n", newline="\n")
        self.installed = self.root / "build_dir/target-fixture/root-airoha/lib/firmware/airoha"
        self.installed.mkdir(parents=True, exist_ok=True)
        for name in BINARIES:
            if name in blobs:
                (self.installed / name).write_bytes(blobs[name])

    def test_original_pair_and_license_are_preserved(self):
        collect_stock_npu(self.root, self.output)
        for name, data in self.blobs.items():
            self.assertEqual((self.output / "npu" / name).read_bytes(), data)

    def test_replaced_program_or_data_rejects_image(self):
        for name in BINARIES:
            with self.subTest(name=name):
                (self.installed / name).write_bytes(b"stale-fdk-cache")
                with self.assertRaisesRegex(ValueError, "replaced NPU blob"):
                    collect_stock_npu(self.root, self.output)
                (self.installed / name).write_bytes(self.blobs[name])
        self.assertFalse(self.output.exists())

    def test_corrupted_archive_rejected(self):
        with self.archive.open("ab") as archive:
            archive.write(b"corrupt")
        with self.assertRaisesRegex(ValueError, "checksum mismatch"):
            collect_stock_npu(self.root, self.output)

    def test_each_modified_recipe_rejected(self):
        for name in RECIPES:
            with self.subTest(name=name):
                path = self.root / name
                saved = path.read_bytes()
                path.write_bytes(saved + b"# replacement\n")
                with self.assertRaisesRegex(ValueError, "recipe was modified"):
                    stock_npu_info(self.root)
                path.write_bytes(saved)

    def test_committed_recipe_change_rejected_against_official_ancestor(self):
        with (self.root / RECIPES[1]).open("a") as recipe:
            recipe.write("# committed vendor change\n")
        self.commit()
        with self.assertRaisesRegex(ValueError, "recipe was modified"):
            stock_npu_info(self.root)

    def test_leftover_fdk_package_rejected(self):
        (self.root / "package/firmware/airoha-npu-fdk").mkdir()
        with self.assertRaisesRegex(ValueError, "FDK replacement package remains"):
            stock_npu_info(self.root)

    def test_missing_official_pair_rejected(self):
        self.write_archive({BINARIES[0]: self.blobs[BINARIES[0]], "LICENSE": b"terms"})
        self.commit()
        (self.base / "source-stack.json").unlink()
        with self.assertRaisesRegex(ValueError, "missing required"):
            collect_stock_npu(self.root, self.output)

    def test_ambiguous_rootfs_rejected(self):
        (self.root / "build_dir/target-second/root-airoha").mkdir(parents=True)
        with self.assertRaisesRegex(ValueError, "exactly one image rootfs"):
            collect_stock_npu(self.root, self.output)

    def test_firmware_identity_changes_package_cache_input(self):
        info = stock_npu_info(self.root)
        changed = {**info, "archive_sha256": "0" * 64}
        self.assertNotEqual(npu_identity(info), npu_identity(changed))
        self.assertEqual(npu_identity(info), npu_identity(dict(reversed(list(info.items())))))


if __name__ == "__main__":
    unittest.main()
