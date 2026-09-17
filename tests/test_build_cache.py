"""Regression tests for incremental reuse without hiding changed build inputs."""
import importlib.util
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def module(name, file):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / file)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


cache = module("build_cache", "build-cache.py")
prune = module("prune_caches", "prune-caches.py")
meta = module("cache_meta", "build-meta.py")


class SourceTimestamps(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.recipe = self.root / "package/example/Makefile"
        self.recipe.parent.mkdir(parents=True)
        self.recipe.write_text("recipe")
        self.input = self.recipe.with_name("input.c")
        self.input.write_text("original source")
        for path in (self.recipe, self.input):
            os.utime(path, ns=(1_600_000_000_000_000_000,) * 2)

    def test_unchanged_content_recovers_old_mtime_but_changed_content_does_not(self):
        previous = cache.source_state(self.root)
        self.recipe.touch()
        self.input.write_text("new source")
        modified = self.input.stat().st_mtime_ns
        cache.restore_mtimes(self.root, previous)
        self.assertEqual(self.recipe.stat().st_mtime_ns, previous["package/example/Makefile"][3])
        self.assertEqual(self.input.read_text(), "new source")
        self.assertEqual(self.input.stat().st_mtime_ns, modified)

    def test_deleted_input_invalidates_the_package_recipe(self):
        previous = cache.source_state(self.root)
        self.input.unlink()
        cache.restore_mtimes(self.root, previous)
        self.assertGreater(self.recipe.stat().st_mtime_ns, previous["package/example/Makefile"][3])

    def test_configuration_is_never_overwritten_or_backdated_after_change(self):
        config = self.root / ".config"
        config.write_text("CONFIG_PACKAGE_one=y\n")
        previous = cache.source_state(self.root)
        config.write_text("CONFIG_PACKAGE_two=y\n")
        modified = config.stat().st_mtime_ns
        cache.restore_mtimes(self.root, previous)
        self.assertEqual(config.read_text(), "CONFIG_PACKAGE_two=y\n")
        self.assertEqual(config.stat().st_mtime_ns, modified)

    def test_source_manifest_excludes_signing_keys_git_and_build_outputs(self):
        for name in ("private-key.pem", "key-build", "package/example/.git/config", "build_dir/host/output"):
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("not source")
        self.assertEqual(set(cache.source_state(self.root)), {"package/example/Makefile", "package/example/input.c"})

    def test_snapshot_relocation_is_rejected_before_touching_build_products(self):
        import json
        snapshot = self.root / "cache"
        snapshot.mkdir()
        (snapshot / "products.tar.zst").write_bytes(b"unused")
        (snapshot / "state.json").write_text(json.dumps(
            {"schema": 2, "kind": "build", "key": "key", "workspace": "/old/workspace"}))
        self.assertFalse(cache.restore(self.root, snapshot, "build", "key"))

    @unittest.skipUnless(sys.platform.startswith("linux") and shutil.which("zstd"), "requires Linux tar/zstd")
    def test_real_snapshot_roundtrip_preserves_products_and_new_sources(self):
        snapshot = self.root / "snapshot"
        for name in ("build_dir/host/tool", "staging_dir/host/bin/tool", "build_dir/toolchain-test/compiler",
                     "staging_dir/toolchain-test/bin/compiler", "build_dir/target-test/kernel.o",
                     "staging_dir/target-test/usr/lib/libtest.so", "staging_dir/hostpkg/bin/helper"):
            file = self.root / name
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_text(name)
        (self.root / "private-key.pem").write_text("must not be archived")
        cache.save(self.root, snapshot, "build", "key")
        self.input.write_text("new source after snapshot")
        (self.root / "private-key.pem").write_text("new signing key")
        shutil.rmtree(self.root / "build_dir")
        shutil.rmtree(self.root / "staging_dir")
        self.assertTrue(cache.restore(self.root, snapshot, "build", "key"))
        self.assertEqual(self.input.read_text(), "new source after snapshot")
        self.assertEqual((self.root / "private-key.pem").read_text(), "new signing key")
        self.assertTrue((self.root / "staging_dir/hostpkg/bin/helper").is_file())
        cache.save(self.root, snapshot, "toolchain", "toolchain-key")
        self.assertTrue(cache.restore(self.root, snapshot, "toolchain", "toolchain-key"))
        self.assertTrue((self.root / "staging_dir/toolchain-test/bin/compiler").is_file())
        self.assertFalse((self.root / "build_dir/target-test").exists())


class CacheKeys(unittest.TestCase):
    def test_new_unselected_feed_package_does_not_discard_build_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / ".config"
            path.write_text('CONFIG_PACKAGE_one=y\n')
            before = meta.config_digest(path)
            path.write_text('CONFIG_PACKAGE_one=y\n# CONFIG_PACKAGE_new is not set\n')
            self.assertEqual(before, meta.config_digest(path))

    def test_package_change_reuses_toolchain_but_not_incompatible_build_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / ".config"
            path.write_text('CONFIG_GCC_VERSION="14"\nCONFIG_PACKAGE_one=y\n')
            toolchain, build = meta.config_digest(path, True), meta.config_digest(path)
            path.write_text('CONFIG_GCC_VERSION="14"\nCONFIG_PACKAGE_two=y\n')
            self.assertEqual(toolchain, meta.config_digest(path, True))
            self.assertNotEqual(build, meta.config_digest(path))
            path.write_text('CONFIG_GCC_VERSION="15"\nCONFIG_PACKAGE_two=y\n')
            self.assertNotEqual(toolchain, meta.config_digest(path, True))

    def test_release_label_does_not_rebuild_toolchain(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / ".config"
            path.write_text('CONFIG_VERSION_NUMBER="old"\nCONFIG_GCC_VERSION="14"\n')
            old = meta.config_digest(path, True)
            path.write_text('CONFIG_VERSION_NUMBER="new"\nCONFIG_GCC_VERSION="14"\n')
            self.assertEqual(old, meta.config_digest(path, True))


class CacheRetention(unittest.TestCase):
    def test_never_deletes_last_good_cache_when_new_upload_is_missing(self):
        items = [{"id": 1, "key": "ours-build-old", "ref": "refs/heads/main"}]
        self.assertEqual(prune.candidates(items, "ours", {"build": "ours-build-new"}, "refs/heads/main"), [])

    def test_deletes_only_replaced_family_on_current_branch_and_host(self):
        items = [{"id": n, "key": key, "ref": ref} for n, key, ref in (
            (1, "ours-build-old", "refs/heads/main"), (2, "ours-build-new", "refs/heads/main"),
            (3, "other-build-old", "refs/heads/main"), (4, "ours-build-old", "refs/heads/topic"),
            (5, "ours-toolchain-old", "refs/heads/main"))]
        self.assertEqual(prune.candidates(items, "ours", {"build": "ours-build-new"}, "refs/heads/main"), [1])


if __name__ == "__main__":
    unittest.main()
