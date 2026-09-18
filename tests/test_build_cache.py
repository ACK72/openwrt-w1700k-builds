"""Regression tests for incremental reuse without hiding changed build inputs."""
import importlib.util
import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock
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

    def test_changed_vermagic_restores_only_toolchain_from_compatible_snapshot(self):
        self.root = self.root / "openwrt"
        self.root.mkdir()
        snapshot = self.root / "cache"
        snapshot.mkdir()
        (snapshot / "products.tar.zst").write_bytes(b"fixture")
        base, toolchain = "a" * 64, "b" * 64
        (self.root.parent / "keys.env").write_text(f"build-base={base}\ntoolchain={toolchain}\n")
        self.addCleanup((self.root.parent / "keys.env").unlink)
        for old in ({"key": base}, {"key": "old-build", "build-base": base, "toolchain": toolchain}):
            metadata = {"schema": 2, "kind": "build", "workspace": str(self.root.resolve()), "inputs": {}, **old}
            (snapshot / "state.json").write_text(json.dumps(metadata))
            with mock.patch.object(cache.subprocess, "run") as run, mock.patch.object(cache, "products") as products:
                self.assertEqual(cache.restore(self.root, snapshot, "build", "new-build"), "toolchain")
            self.assertEqual(run.call_args.args[0][-5:], ["--wildcards", "build_dir/host", "staging_dir/host",
                                                        "build_dir/toolchain-*", "staging_dir/toolchain-*"])
            products.assert_called_once_with(self.root, "toolchain")
        metadata["build-base"] = "c" * 64
        (snapshot / "state.json").write_text(json.dumps(metadata))
        with mock.patch.object(cache.subprocess, "run") as run:
            self.assertFalse(cache.restore(self.root, snapshot, "build", "new-build"))
        run.assert_not_called()

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

    @unittest.skipUnless(sys.platform.startswith("linux") and shutil.which("zstd"), "requires Linux tar/zstd")
    def test_real_toolchain_extraction_from_legacy_full_snapshot_excludes_targets(self):
        self.root = self.root / "openwrt"
        self.root.mkdir()
        base = "a" * 64
        snapshot = self.root / "snapshot"
        for name in ("build_dir/host/tool", "staging_dir/host/bin/tool", "build_dir/toolchain-test/compiler",
                     "staging_dir/toolchain-test/bin/compiler", "build_dir/target-test/kernel.o",
                     "staging_dir/target-test/usr/lib/libtest.so", "staging_dir/hostpkg/bin/helper"):
            path = self.root / name
            path.parent.mkdir(parents=True)
            path.write_text(name)
        cache.save(self.root, snapshot, "build", base)
        (self.root.parent / "keys.env").write_text(f"build-base={base}\ntoolchain={'b' * 64}\n")
        self.addCleanup((self.root.parent / "keys.env").unlink)
        self.assertEqual(cache.restore(self.root, snapshot, "build", "new-vermagic-build"), "toolchain")
        self.assertTrue((self.root / "build_dir/toolchain-test/compiler").is_file())
        self.assertTrue((self.root / "staging_dir/host/bin/tool").is_file())
        self.assertFalse((self.root / "build_dir/target-test").exists())
        self.assertFalse((self.root / "staging_dir/target-test").exists())
        self.assertFalse((self.root / "staging_dir/hostpkg").exists())


class CacheKeys(unittest.TestCase):
    def test_distfeeds_changes_preserve_toolchain_and_only_vermagic_discards_kernel(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ("scripts", "configs", "package", "patches", ".github", "LICENSES"):
                (root / name).mkdir()
            openwrt = root / ".work/openwrt"
            (openwrt / "feeds").mkdir(parents=True)
            (openwrt / "Makefile").write_text("source")
            (openwrt / ".config").write_text('CONFIG_GCC_VERSION="14"\n')
            vermagic = openwrt / "files/etc/vermagic.txt"
            distfeeds = openwrt / "files/etc/apk/repositories.d/distfeeds.list"
            distfeeds.parent.mkdir(parents=True)
            vermagic.write_text("a" * 32 + "\n")
            distfeeds.write_text("official feeds A\n")

            def state():
                with mock.patch.object(meta, "ROOT", root), \
                        mock.patch.object(meta, "git", side_effect=lambda path, *args: "Makefile" if args[0] == "ls-files" else "a" * 40), \
                        mock.patch.object(meta.subprocess, "check_output", return_value="host-tools"), \
                        contextlib.redirect_stdout(io.StringIO()):
                    meta.keys(openwrt, root / "npu")
                return json.loads((openwrt.parent / "build-state.json").read_text())

            first = state()
            distfeeds.write_text("official feeds B\n")
            second = state()
            self.assertEqual(first["toolchain"], second["toolchain"])
            self.assertEqual(first["build"], second["build"])
            self.assertNotEqual(first["fingerprint"], second["fingerprint"])
            vermagic.write_text("b" * 32 + "\n")
            third = state()
            self.assertEqual(second["toolchain"], third["toolchain"])
            self.assertNotEqual(second["build"], third["build"])
            self.assertEqual(second["build_base"], third["build_base"])
            self.assertNotEqual(second["fingerprint"], third["fingerprint"])

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
    def item(self, number, kind, size, ref="refs/heads/main", host="X64"):
        return {"id": number, "key": f"w1700k-v2-Linux-{host}-{kind}-{number}",
                "size_in_bytes": size, "ref": ref, "last_accessed_at": str(number)}

    def plan(self, items, size, reservations=None):
        return prune.reservation_plan(items, reservations or {}, "w1700k-v2-Linux-X64-build-new",
                                      size, "w1700k-v2-Linux-X64-build-", "refs/heads/main")

    def test_current_real_sizes_require_replacing_old_snapshot_before_upload(self):
        items = [self.item(1, "build", 5_021_524_373), self.item(2, "dl", 1_545_716_047),
                 self.item(3, "ccache", 707_094_988)]
        remove = self.plan(items, 5_200_000_000)
        self.assertEqual(remove, [1])
        self.assertLess(sum(i["size_in_bytes"] for i in items if i["id"] not in remove) + 5_200_000_000,
                        prune.BUDGET)

    def test_no_eviction_when_all_cache_generations_fit(self):
        self.assertEqual(self.plan([self.item(1, "build", 1_000_000_000)], 1_000_000_000), [])

    def test_pending_uploads_are_counted_even_when_rest_listing_is_stale(self):
        reservations = {"w1700k-v2-Linux-X64-dl-new": 5_000_000_000}
        self.assertIsNone(self.plan([], 5_000_000_000, reservations))

    def test_confirmed_upload_is_not_double_counted_or_evicted(self):
        item = self.item(1, "build", 5_000_000_000)
        reservations = {item["key"]: 5_100_000_000}
        self.assertEqual(self.plan([item], 3_000_000_000, reservations), [])
        self.assertIsNone(self.plan([item], 5_000_000_000, reservations))

    def test_architectures_share_budget_but_unrelated_and_other_branch_caches_are_preserved(self):
        arm = self.item(1, "build", 5_000_000_000, host="ARM64")
        self.assertEqual(self.plan([arm], 5_000_000_000), [1])
        arm["ref"] = "refs/heads/topic"
        self.assertIsNone(self.plan([arm], 5_000_000_000))
        arm["ref"], arm["key"] = "refs/heads/main", "unrelated-cache"
        self.assertIsNone(self.plan([arm], 5_000_000_000))

    def test_oversized_cache_skips_upload_without_evicting_anything(self):
        self.assertIsNone(self.plan([self.item(1, "build", 1)], prune.BUDGET + 1))

    def test_upload_bound_accounts_for_metadata_and_compression_expansion(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "archive.zst").write_bytes(os.urandom(1000))
            self.assertGreater(prune.upload_bound(root), 1000 + 64 * 1024**2)

    def test_never_deletes_last_good_cache_when_new_upload_is_missing(self):
        items = [{"id": 1, "key": "ours-build-old", "ref": "refs/heads/main"}]
        self.assertEqual(prune.candidates(items, "ours", {"build": "ours-build-new"}, "refs/heads/main"), [])

    def test_deletes_only_replaced_family_on_current_branch_and_host(self):
        items = [{"id": n, "key": key, "ref": ref} for n, key, ref in (
            (1, "ours-build-old", "refs/heads/main"), (2, "ours-build-new", "refs/heads/main"),
            (3, "other-build-old", "refs/heads/main"), (4, "ours-build-old", "refs/heads/topic"),
            (5, "ours-toolchain-old", "refs/heads/main"))]
        self.assertEqual(prune.candidates(items, "ours", {"build": "ours-build-new"}, "refs/heads/main"), [1])


class CacheReservation(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        previous = Path.cwd()
        os.chdir(self.root)
        self.addCleanup(os.chdir, previous)
        self.env = mock.patch.dict(os.environ, {
            "GH_REPO": "owner/repo", "GITHUB_REF": "refs/heads/main",
            "CACHE_PREFIX": "w1700k-v2-Linux-X64", "GITHUB_OUTPUT": str(self.root / "output"),
        })
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_replaces_old_snapshot_and_records_pending_upload(self):
        key = "w1700k-v2-Linux-X64-build-new"
        old = {"id": 1, "key": "w1700k-v2-Linux-X64-build-old",
               "ref": "refs/heads/main", "size_in_bytes": 5_000_000_000}
        with mock.patch.object(prune, "list_caches", return_value=[old]), \
                mock.patch.object(prune, "upload_bound", return_value=5_100_000_000), \
                mock.patch.object(prune.subprocess, "run") as run:
            self.assertTrue(prune.reserve("build", self.root, key))
        run.assert_called_once_with(
            ["gh", "api", "--method", "DELETE", "repos/owner/repo/actions/caches/1"],
            check=True, timeout=60)
        self.assertEqual(json.loads((self.root / ".work/cache-budget.json").read_text()),
                         {key: 5_100_000_000})

    def test_early_npu_upload_preserves_build_cache_before_restore(self):
        old = {"id": 1, "key": "w1700k-v2-Linux-X64-build-old",
               "ref": "refs/heads/main", "size_in_bytes": prune.BUDGET}
        with mock.patch.object(prune, "list_caches", return_value=[old]), \
                mock.patch.object(prune, "upload_bound", return_value=100_000_000), \
                mock.patch.object(prune.subprocess, "run") as run:
            self.assertFalse(prune.reserve("npu", self.root, "w1700k-v2-Linux-X64-npu-new"))
        run.assert_not_called()
        self.assertFalse((self.root / ".work/cache-budget.json").exists())

    def test_shared_distfeeds_cache_preserves_build_cache_before_restore(self):
        key = "w1700k-v2-shared-distfeeds-new"
        old = {"id": 1, "key": "w1700k-v2-Linux-X64-build-old",
               "ref": "refs/heads/main", "size_in_bytes": prune.BUDGET}
        with mock.patch.object(prune, "list_caches", return_value=[old]), \
                mock.patch.object(prune, "upload_bound", return_value=100_000_000), \
                mock.patch.object(prune.subprocess, "run") as run:
            self.assertFalse(prune.reserve("distfeeds", self.root, key))
        run.assert_not_called()
        with mock.patch.object(prune, "list_caches", return_value=[]), \
                mock.patch.object(prune, "upload_bound", return_value=100_000_000):
            self.assertTrue(prune.reserve("distfeeds", self.root, key))

    def test_api_failure_disables_upload_instead_of_ignoring_budget(self):
        with mock.patch.object(sys, "argv", ["prune-caches.py", "reserve", "build", ".",
                                            "w1700k-v2-Linux-X64-build-new"]), \
                mock.patch.object(prune, "list_caches", side_effect=OSError("API unavailable")), \
                mock.patch.object(prune.subprocess, "run") as run:
            prune.main()
        run.assert_not_called()
        self.assertEqual((self.root / "output").read_text(), "save=false\n")


if __name__ == "__main__":
    unittest.main()
