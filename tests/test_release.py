"""Publication must never trade the last working firmware for a partial upload."""
import copy
import importlib.util
import json
import subprocess
import tempfile
import tarfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("release", ROOT / "scripts/release.py")
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)
FINGERPRINT = "a" * 64
COMMIT = "b" * 40


def record(number, **overrides):
    result = {"id": number, "tag_name": f"{release.PREFIX}{number}-1", "draft": False,
              "prerelease": False, "published_at": f"2026-09-{number:02d}T00:00:00Z",
              "body": f"{release.MARKER}\n<!-- fingerprint:{FINGERPRINT} -->",
              "assets": [{"name": name, "size": 1, "state": "uploaded"} for name in
                         ("image-sysupgrade.itb", "SHA256SUMS", "build-manifest.json", "packages.tar.zst", "public-key.pem")]}
    result.update(overrides)
    return result


class Retention(unittest.TestCase):
    def test_publish_only_retry_keeps_original_build_attempt(self):
        with patch.dict(release.os.environ, {"GH_REPO": "owner/repo", "GITHUB_RUN_ID": "10",
                        "GITHUB_RUN_ATTEMPT": "2", "RELEASE_ATTEMPT": "1", "GITHUB_SHA": COMMIT}), \
             patch("sys.argv", ["release.py", "publish", "payload", "output"]), \
             patch.object(release, "publish") as publish:
            release.main()
        self.assertEqual(publish.call_args.args[-2], "1")

    def test_keep_newest_three_and_preserve_unrelated_drafts_and_prereleases(self):
        items = [record(n) for n in range(1, 6)]
        items += [record(6, draft=True), record(7, prerelease=True), record(8, tag_name="unrelated")]
        self.assertEqual([r["id"] for r in release.prune_candidates(items)], [2, 1])

    def test_incomplete_upload_and_unmanaged_tag_do_not_suppress_build(self):
        self.assertTrue(release.already_published([record(1)], FINGERPRINT))
        for item in (record(1, assets=[]), record(1, draft=True), record(1, prerelease=True),
                     record(1, body="unmanaged"), record(1, tag_name="unrelated")):
            self.assertFalse(release.already_published([item], FINGERPRINT))
        self.assertFalse(release.already_published([record(1)], "c" * 64))


class ReleaseImage(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "payload"
        self.target = self.root / "firmware"
        self.target.mkdir(parents=True)
        self.image = self.target / "openwrt-gemtek_w1700k-ubi-squashfs-sysupgrade.itb"
        self.image.write_bytes(bytes.fromhex("d00dfeed") + b"fit-image-fixture")
        self.profile = {"target": release.TARGET, "version_code": "r36347-e304e64c26", "profiles": {release.DEVICE: {
            "supported_devices": [release.SUPPORTED_DEVICE], "images": [{"type": "sysupgrade",
                "name": self.image.name, "size": self.image.stat().st_size, "sha256": release.sha256(self.image)}]}}}
        self.metadata = {"version": {"target": release.TARGET}, "compat_version": "2.0",
                         "supported_devices": ["legacy compatibility message"],
                         "new_supported_devices": [release.SUPPORTED_DEVICE]}
        self.write_metadata()
        manifest = {"fingerprint": FINGERPRINT, "builder_commit": COMMIT,
                    "build_type": "release", "openwrt": "c" * 40, "npu": "d" * 40,
                    "built_at": "2026-09-17T15:01:00+00:00", "changelog": ["e304e64c26 Firmware update"]}
        (self.root / "build-manifest.json").write_text(json.dumps(manifest))
        for name in ("openwrt.config", "config.diff", "feeds.lock", "packages.tar.zst", "public-key.pem"):
            (self.root / name).write_text("fixture\n")
        self.checksums()

    def write_metadata(self):
        (self.target / "profiles.json").write_text(json.dumps(self.profile))
        (self.root / "image-metadata.json").write_text(json.dumps(self.metadata))

    def checksums(self):
        (self.root / "SHA256SUMS").write_text("".join(
            f"{release.sha256(p)}  {p.relative_to(self.root).as_posix()}\n"
            for p in sorted(self.root.rglob("*")) if p.is_file() and p.name != "SHA256SUMS"))

    def test_accepts_ubi2_metadata_and_prepares_standalone_installable_asset(self):
        output = Path(self.temp.name) / "assets"
        release.prepare(self.root, output)
        release.verify_checksums(output)
        self.assertEqual((output / self.image.name).read_bytes(), self.image.read_bytes())
        self.assertEqual(len(list(output.iterdir())), 5)
        with tarfile.open(output / "build-info.tar.gz") as archive:
            self.assertEqual(json.load(archive.extractfile("build-manifest.json"))["builder_commit"], COMMIT)
            self.assertIn("profiles.json", archive.getnames())

    def test_build_info_archive_has_repeatable_checksums(self):
        first, second = (Path(self.temp.name) / name for name in ("first", "second"))
        release.prepare(self.root, first)
        (self.root / "build-manifest.json").touch()
        release.prepare(self.root, second)
        self.assertEqual((first / "SHA256SUMS").read_bytes(), (second / "SHA256SUMS").read_bytes())

    def test_notes_show_firmware_revision_build_date_and_source_changes(self):
        manifest = json.loads((self.root / "build-manifest.json").read_text())
        title, notes = release.release_notes(self.root, manifest, "owner/repo", "10")
        self.assertEqual(title, "ubi2-oc_2026.09.18_r36347-e304e64c26")
        self.assertIn("    e304e64c26 Firmware update", notes)
        self.assertIn(f"/tree/{COMMIT}", notes)
        self.assertIn("<!-- fingerprint:", notes)

    def test_wrong_device_wrong_target_and_missing_image_are_rejected(self):
        for mutation in (lambda: self.metadata.update(new_supported_devices=["other,board"]),
                         lambda: self.metadata["version"].update(target="other/target"),
                         lambda: self.profile["profiles"][release.DEVICE].update(images=[])):
            old_meta, old_profile = copy.deepcopy(self.metadata), copy.deepcopy(self.profile)
            mutation()
            self.write_metadata()
            with self.assertRaises(ValueError):
                release.verify_image(self.target, self.root / "image-metadata.json")
            self.metadata, self.profile = old_meta, old_profile

    def test_corrupted_image_and_checksum_path_escape_are_rejected(self):
        self.image.write_bytes(b"corrupted")
        with self.assertRaisesRegex(ValueError, "checksum"):
            release.verify_image(self.target, self.root / "image-metadata.json")
        (self.root / "SHA256SUMS").write_text(f"{'a'*64}  ../outside\n")
        with self.assertRaisesRegex(ValueError, "Invalid checksum"):
            release.verify_checksums(self.root)

    def test_no_release_is_published_or_pruned_after_upload_failure(self):
        calls = []
        def fake_gh(*args):
            calls.append(args)
            if args[:2] == ("release", "upload"):
                raise subprocess.CalledProcessError(1, args)
            return ""
        old = [record(n) for n in range(1, 4)]
        with patch.object(release, "releases", side_effect=[old, old + [record(10, draft=True)]]), \
             patch.object(release, "gh", side_effect=fake_gh):
            with self.assertRaises(subprocess.CalledProcessError):
                release.publish(self.root, Path(self.temp.name) / "assets", "owner/repo", "10", "1", COMMIT)
        self.assertTrue(any(c[:2] == ("release", "create") and "--draft" in c for c in calls))
        self.assertFalse(any(c[:2] in (("release", "edit"), ("release", "delete")) for c in calls))

    def test_publish_verifies_digests_before_visibility_and_prunes_afterwards(self):
        calls = []
        output = Path(self.temp.name) / "assets"
        new = record(10, draft=True)
        old = [record(n) for n in range(1, 4)]
        def fake_gh(*args):
            calls.append(args)
            if args[:2] == ("release", "upload"):
                new["assets"] = [{"name": p.name, "state": "uploaded", "size": p.stat().st_size,
                                  "digest": "sha256:" + release.sha256(p)} for p in output.iterdir()]
            if args[0] == "api" and "--method" not in args:
                # A draft has an ID but no tag; the old /releases/tags lookup fails.
                self.assertEqual(args[1], "repos/owner/repo/releases/10")
                return json.dumps(new)
            if args[:3] == ("api", "--method", "PATCH"):
                self.assertIn("target_commitish=main", args)
                new["draft"] = False
            return ""
        def listing(_repo):
            return old if not calls else old + [new]
        with patch.object(release, "releases", side_effect=listing), patch.object(release, "gh", side_effect=fake_gh):
            release.publish(self.root, output, "owner/repo", "10", "1", COMMIT)
        create = next(c for c in calls if c[:2] == ("release", "create"))
        self.assertEqual(create[create.index("--target") + 1], "main")
        self.assertNotIn(COMMIT, create)
        edit = next(i for i, c in enumerate(calls) if c[:3] == ("api", "--method", "PATCH"))
        deletion = next(i for i, c in enumerate(calls) if c[:2] == ("release", "delete"))
        self.assertLess(edit, deletion)
        self.assertEqual(calls[deletion][2], f"{release.PREFIX}1-1")

    def test_digest_mismatch_keeps_draft_and_previous_releases(self):
        calls = []
        new = record(10, draft=True)
        def fake_gh(*args):
            calls.append(args)
            if args[0] == "api":
                output = Path(self.temp.name) / "assets"
                new["assets"] = [{"name": p.name, "state": "uploaded", "size": p.stat().st_size,
                                  "digest": "sha256:" + "0" * 64} for p in output.iterdir()]
                return json.dumps(new)
            return ""
        with patch.object(release, "releases", return_value=[new]), patch.object(release, "gh", side_effect=fake_gh):
            with self.assertRaisesRegex(RuntimeError, "digest mismatch"):
                release.publish(self.root, Path(self.temp.name) / "assets", "owner/repo", "10", "1", COMMIT)
        self.assertFalse(any(c[:3] == ("api", "--method", "PATCH") or c[:2] == ("release", "delete") for c in calls))


if __name__ == "__main__":
    unittest.main()
