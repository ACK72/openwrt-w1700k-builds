"""Official image pinning, paired metadata reuse, and compiled firmware checks."""
import contextlib
import importlib.util
import io
import json
import shutil
import struct
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("distfeeds", ROOT / "scripts/distfeeds.py")
feeds = importlib.util.module_from_spec(spec)
spec.loader.exec_module(feeds)
MAGIC = "a" * 32
LIST = ("# official feed fixture\n" + feeds.BASE + "packages/packages.adb\n" + feeds.BASE +
        f"kmods/6.18.52-1-{MAGIC}/packages.adb\n" +
        "https://downloads.openwrt.org/snapshots/packages/aarch64_cortex-a53/telephony/packages.adb\n" +
        "https://downloads.openwrt.org/snapshots/packages/aarch64_cortex-a53/video/packages.adb\n").encode()


def image_fixture():
    data = bytearray(96)
    data[:4] = b"hsqs"
    struct.pack_into("<HH", data, 28, 4, 0)
    struct.pack_into("<Q", data, 40, len(data))
    return b"locally-unused-official-kernel" + data


class Distfeeds(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.cache = self.root / "cache"
        self.source_path = self.root / "distfeeds-source.json"
        self.image = image_fixture()
        self.source = {"url": feeds.BASE + feeds.IMAGE, "sha256": feeds.sha256(self.image)}
        self.source_path.write_text(json.dumps(self.source))

    def populate(self):
        with mock.patch.object(feeds, "fetch", side_effect=[self.image, b""]), \
                mock.patch.object(feeds, "extract", return_value=LIST):
            feeds.prepare(self.source_path, self.cache)

    def test_resolve_uses_exact_image_checksum_and_shared_content_key(self):
        manifest = self.profiles([self.profile_image()])
        output = io.StringIO()
        with mock.patch.object(feeds, "fetch", return_value=manifest), contextlib.redirect_stdout(output):
            feeds.resolve(self.source_path)
        self.assertEqual(json.loads(self.source_path.read_text()), self.source)
        self.assertIn("cache-key=w1700k-v2-shared-distfeeds-", output.getvalue())
        self.assertTrue(output.getvalue().strip().endswith(self.source["sha256"]))

    def test_missing_or_ambiguous_official_checksum_is_rejected(self):
        image = self.profile_image()
        for manifest in (self.profiles([]), self.profiles([image, image]),
                         self.profiles([{**image, "sha256": "invalid"}])):
            with self.subTest(manifest=manifest), mock.patch.object(feeds, "fetch", return_value=manifest):
                with self.assertRaisesRegex(ValueError, "missing or ambiguous"):
                    feeds.resolve(self.source_path)

    def profile_image(self):
        return {"name": feeds.IMAGE, "sha256": self.source["sha256"],
                "type": "sysupgrade", "filesystem": "squashfs"}

    def profiles(self, images):
        return json.dumps({"target": "airoha/an7581", "profiles": {
            "airoha_an7581-evb": {"images": images}}}).encode()

    def test_cold_cache_keeps_exact_list_and_only_three_small_files(self):
        self.populate()
        self.assertEqual((self.cache / "distfeeds.list").read_bytes(), LIST)
        self.assertEqual((self.cache / "vermagic.txt").read_bytes(), (MAGIC + "\n").encode())
        self.assertEqual({p.name for p in self.cache.iterdir()}, {"distfeeds.list", "vermagic.txt", "source.json"})

    def test_warm_cache_does_not_download_or_extract_image(self):
        self.populate()
        with mock.patch.object(feeds, "fetch", return_value=b"") as fetch, \
                mock.patch.object(feeds, "extract") as extract:
            feeds.prepare(self.source_path, self.cache)
        extract.assert_not_called()
        fetch.assert_called_once_with(feeds.parse_feeds(LIST)["kmods_url"], 0, "HEAD")

    def test_corrupt_or_stale_cache_is_refreshed(self):
        for corruption in ("file", "source"):
            with self.subTest(corruption=corruption):
                self.populate()
                if corruption == "file":
                    (self.cache / "vermagic.txt").write_text("bad")
                else:
                    metadata = json.loads((self.cache / "source.json").read_text())
                    metadata["source"]["sha256"] = "b" * 64
                    (self.cache / "source.json").write_text(json.dumps(metadata))
                with mock.patch.object(feeds, "fetch", side_effect=[self.image, b""]) as fetch, \
                        mock.patch.object(feeds, "extract", return_value=LIST) as extract:
                    feeds.prepare(self.source_path, self.cache)
                self.assertEqual(fetch.call_count, 2)
                extract.assert_called_once()
                feeds.read_cache(self.cache, self.source)

    def test_snapshot_publication_race_is_rejected_before_extraction(self):
        with mock.patch.object(feeds, "fetch", return_value=self.image + b"changed"), \
                mock.patch.object(feeds, "extract") as extract:
            with self.assertRaisesRegex(ValueError, "checksum changed"):
                feeds.prepare(self.source_path, self.cache)
        extract.assert_not_called()
        self.assertFalse(self.cache.exists())

    def test_missing_repository_does_not_commit_a_new_cache(self):
        with mock.patch.object(feeds, "fetch", side_effect=[self.image, OSError("404")]), \
                mock.patch.object(feeds, "extract", return_value=LIST):
            with self.assertRaisesRegex(OSError, "404"):
                feeds.prepare(self.source_path, self.cache)
        self.assertFalse(self.cache.exists())

    def test_invalid_feed_lists_are_rejected(self):
        for data in (b"", b"<html>Error</html>", LIST + LIST,
                     LIST.replace(b"airoha/an7581/kmods", b"wrong/target/kmods"),
                     LIST.replace(MAGIC.encode(), b"not-a-kernel-hash"),
                     LIST.replace(b"https://downloads.openwrt.org", b"https://example.org")):
            with self.subTest(data=data), self.assertRaises(ValueError):
                feeds.parse_feeds(data)

    def test_pair_mismatch_is_rejected_even_with_updated_checksums(self):
        self.populate()
        value = ("b" * 32 + "\n").encode()
        (self.cache / "vermagic.txt").write_bytes(value)
        metadata = json.loads((self.cache / "source.json").read_text())
        metadata["files"]["vermagic.txt"] = feeds.sha256(value)
        (self.cache / "source.json").write_text(json.dumps(metadata))
        with self.assertRaisesRegex(ValueError, "same kernel"):
            feeds.read_cache(self.cache)

    def test_squashfs_detection_checks_superblock_and_rejects_ambiguity(self):
        self.assertEqual(feeds.squashfs_offset(self.image), len(b"locally-unused-official-kernel"))
        for data in (b"hsqs", b"not squashfs", self.image + self.image):
            with self.subTest(data=data), self.assertRaises(ValueError):
                feeds.squashfs_offset(data)

    def install(self):
        self.populate()
        openwrt = self.root / "openwrt"
        hook = openwrt / "include/kernel-defaults.mk"
        hook.parent.mkdir(parents=True)
        hook.write_text("cp ../../../files/etc/vermagic.txt $(LINUX_DIR)/.vermagic\n")
        kernel = openwrt / "target/linux/local-kernel-source"
        kernel.parent.mkdir(parents=True)
        kernel.write_bytes(b"own kernel")
        feeds.install(self.cache, openwrt)
        self.assertEqual(kernel.read_bytes(), b"own kernel")
        self.assertEqual((openwrt / "files" / feeds.FEEDS).read_bytes(), LIST)
        return openwrt

    def test_install_and_verify_locally_compiled_kernel_and_rootfs(self):
        openwrt = self.install()
        rootfs = openwrt / "build_dir/target-test/root-airoha"
        kernel = openwrt / "build_dir/target-test/linux-airoha_an7581/linux-6.18.52/.vermagic"
        kernel.parent.mkdir(parents=True)
        kernel.write_text(MAGIC + "\n")
        for relative in feeds.FILES.values():
            target = rootfs / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(openwrt / "files" / relative, target)
        feeds.verify(openwrt)
        kernel.write_text("b" * 32 + "\n")
        with self.assertRaisesRegex(ValueError, "kernel did not use"):
            feeds.verify(openwrt)
        kernel.write_text(MAGIC + "\n")
        (rootfs / feeds.FEEDS).write_bytes(b"autogenerated wrong feeds")
        with self.assertRaisesRegex(ValueError, "rootfs"):
            feeds.verify(openwrt)

    @unittest.skipUnless(shutil.which("mksquashfs") and shutil.which("unsquashfs"), "requires squashfs-tools")
    def test_real_embedded_squashfs_extracts_only_distfeeds(self):
        rootfs = self.root / "fixture-rootfs"
        path = rootfs / feeds.FEEDS
        path.parent.mkdir(parents=True)
        path.write_bytes(LIST)
        squashfs = self.root / "rootfs.squashfs"
        subprocess.run(["mksquashfs", str(rootfs), str(squashfs), "-noappend", "-processors", "1", "-quiet"],
                       check=True, stdout=subprocess.DEVNULL)
        image = self.root / "fixture.bin"
        data = b"own-firmware-header" + squashfs.read_bytes()
        image.write_bytes(data)
        self.assertEqual(feeds.extract(image, feeds.squashfs_offset(data)), LIST)


if __name__ == "__main__":
    unittest.main()
