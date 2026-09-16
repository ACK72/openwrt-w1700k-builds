"""Exercise package replacement and cache invalidation without a full firmware build."""
import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("build_meta", ROOT / "scripts/build-meta.py")
meta = importlib.util.module_from_spec(spec)
spec.loader.exec_module(meta)


def recipe(name):
    return (
        f"Package/{name} = $(call Package/firmware-default,title,,LICENSE.airoha)\n"
        f"define Package/{name}/install\n\t$(CP) vendor.bin $(1)/lib/firmware/\n"
        f"endef\n\n$(eval $(call BuildPackage,{name}))\n"
    )


class NpuIntegration(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.openwrt, self.npu, self.firmware = (root / x for x in ("openwrt", "npu", "firmware"))
        self.recipe = self.openwrt / "package/firmware/linux-firmware/airoha.mk"
        self.recipe.parent.mkdir(parents=True)
        self.npu.mkdir()
        self.firmware.mkdir()
        self.other = recipe("airoha-en7581-npu-firmware") + recipe("airoha-an7583-npu-firmware")
        self.original = recipe(meta.PACKAGE) + self.other
        self.recipe.write_text(self.original)
        (self.openwrt / "rules.mk").write_text("export CCACHE_NOCOMPRESS:=true\n")
        (self.npu / "LICENSE").write_text("MIT license fixture\n")
        for name in meta.BINARIES:
            (self.firmware / name).write_bytes(b"firmware-" + name.encode())
        mock_git = patch.object(meta, "git", return_value="a" * 40)
        mock_git.start()
        self.addCleanup(mock_git.stop)

    def install(self):
        meta.install_npu(self.openwrt, self.npu, self.firmware)

    def test_replaces_only_mt7996_and_keeps_package_owned_files(self):
        self.install()
        self.assertIn(self.other, self.recipe.read_text())
        self.assertNotIn(f"BuildPackage,{meta.PACKAGE}", self.recipe.read_text())
        package = self.openwrt / "package/firmware/airoha-npu-fdk"
        self.assertIn("PKG_VERSION:=0~aaaaaaaaaaaa", (package / "Makefile").read_text())
        for name in meta.BINARIES:
            self.assertEqual((package / "files" / name).read_bytes(), (self.firmware / name).read_bytes())
        self.assertEqual((package / "files/LICENSE").read_text(), (self.npu / "LICENSE").read_text())
        self.assertIn("CCACHE_COMPRESS:=true", (self.openwrt / "rules.mk").read_text())

    def test_second_run_is_idempotent(self):
        self.install()
        once = self.recipe.read_bytes()
        self.install()
        self.assertEqual(once, self.recipe.read_bytes())

    def test_missing_pair_does_not_remove_vendor_recipe(self):
        (self.firmware / meta.BINARIES[1]).unlink()
        with self.assertRaisesRegex(RuntimeError, "Missing/empty"):
            self.install()
        self.assertEqual(self.original, self.recipe.read_text())

    def test_empty_pair_is_rejected(self):
        (self.firmware / meta.BINARIES[0]).write_bytes(b"")
        with self.assertRaisesRegex(RuntimeError, "Missing/empty"):
            self.install()

    def test_changed_upstream_definition_is_rejected(self):
        self.recipe.write_text(self.original.replace(" = ", " := "))
        with self.assertRaisesRegex(RuntimeError, "recipe changed"):
            self.install()

    def test_duplicate_package_is_rejected(self):
        self.recipe.write_text(self.original + recipe(meta.PACKAGE))
        with self.assertRaisesRegex(RuntimeError, "recipe changed"):
            self.install()

    def test_marker_does_not_hide_reintroduced_vendor_package(self):
        self.install()
        self.recipe.write_text(self.recipe.read_text() + recipe(meta.PACKAGE))
        with self.assertRaisesRegex(RuntimeError, "duplicate definition"):
            self.install()


class Configuration(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.profile = self.root / "profile"
        self.profile.write_text('CONFIG_PACKAGE_luci=y\n# CONFIG_SDK is not set\n')
        self.config = self.root / ".config"
        self.valid = "".join(f"{name}=y\n" for name in meta.REQUIRED_CONFIG)
        self.valid += 'CONFIG_PACKAGE_luci=y\n# CONFIG_SDK is not set\n'
        self.config.write_text(self.valid)

    def test_current_driver_and_requested_packages_are_accepted(self):
        meta.check_config(self.root, self.profile)

    def test_missing_driver_is_rejected_even_if_not_explicit_in_profile(self):
        self.config.write_text(self.valid.replace('CONFIG_PACKAGE_kmod-mt7996e=y\n', ''))
        with self.assertRaisesRegex(RuntimeError, 'kmod-mt7996e'):
            meta.check_config(self.root, self.profile)

    def test_silently_dropped_luci_app_is_rejected(self):
        self.profile.write_text(self.profile.read_text() + 'CONFIG_PACKAGE_luci-app-wifi7=y\n')
        with self.assertRaisesRegex(RuntimeError, 'luci-app-wifi7'):
            meta.check_config(self.root, self.profile)

    def test_module_cannot_replace_package_requested_in_image(self):
        self.config.write_text(self.valid.replace('CONFIG_PACKAGE_luci=y', 'CONFIG_PACKAGE_luci=m'))
        with self.assertRaisesRegex(RuntimeError, 'requested y, got m'):
            meta.check_config(self.root, self.profile)

    def test_disabled_feature_cannot_be_enabled_silently(self):
        self.config.write_text(self.valid.replace('# CONFIG_SDK is not set', 'CONFIG_SDK=y'))
        with self.assertRaisesRegex(RuntimeError, 'CONFIG_SDK'):
            meta.check_config(self.root, self.profile)


class CacheDigest(unittest.TestCase):
    def test_content_and_path_changes_invalidate_but_mtime_does_not(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            file = root / "input"
            file.write_text("one")
            first = meta.digest_paths(root, ["input"])
            file.touch()
            self.assertEqual(first, meta.digest_paths(root, ["input"]))
            file.write_text("two")
            self.assertNotEqual(first, meta.digest_paths(root, ["input"]))
            file.rename(root / "renamed")
            self.assertNotEqual(first, meta.digest_paths(root, ["renamed"]))

    def test_unlisted_build_products_do_not_poison_source_key(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "Makefile").write_text("source")
            first = meta.digest_paths(root, ["Makefile"])
            (root / "generated-conf").write_bytes(b"executable")
            self.assertEqual(first, meta.digest_paths(root, ["Makefile"]))

    def test_removed_input_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(FileNotFoundError):
                meta.digest_paths(Path(temp), ["missing-input"])


if __name__ == "__main__":
    unittest.main()
