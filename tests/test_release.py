"""Publication must never trade the last working firmware for a partial upload."""
import copy
import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("release", ROOT / "scripts/release.py")
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)
FINGERPRINT = "a" * 64
COMMIT = "b" * 40
IMAGE_NAME = "openwrt-airoha-an7581-gemtek_w1700k-ubi-squashfs-sysupgrade-r36347.itb"


def record(number, **overrides):
    result = {"id": number, "tag_name": f"{release.PREFIX}{number}-1", "draft": False,
              "prerelease": False, "published_at": f"2026-09-{number:02d}T00:00:00Z",
              "body": f"{release.MARKER}\n<!-- fingerprint:{FINGERPRINT} -->",
              "assets": [{"name": name, "size": 1, "state": "uploaded"} for name in
                         ("image-sysupgrade.itb", "SHA256SUMS", "build-manifest.json", "packages.tar.zst", "public-key.pem")]}
    result.update(overrides)
    return result


class Retention(unittest.TestCase):
    def test_new_single_image_releases_and_legacy_releases_share_retention(self):
        image = {"name": IMAGE_NAME, "size": 100, "state": "uploaded"}
        items = [record(n) for n in range(1, 4)] + [record(4, assets=[image])]
        self.assertTrue(release.complete(items[-1]))
        self.assertEqual([r["id"] for r in release.prune_candidates(items)], [1])
        for bad in ([dict(image, state="starter")], [dict(image, size=0)],
                    [dict(image, name="other.itb")], [image, dict(image, name="notes.txt")]):
            self.assertFalse(release.complete(record(5, assets=bad)))

    def test_next_build_deletes_only_managed_drafts_without_deleting_tags(self):
        items = [record(1, draft=True), record(2), record(3, draft=True, body="manual"),
                 record(4, draft=True, tag_name="manual"), record(5, prerelease=True)]
        with patch.object(release, "releases", return_value=items), patch.object(release, "gh") as gh:
            release.clean_drafts("owner/repo")
        gh.assert_called_once_with("api", "--method", "DELETE", "repos/owner/repo/releases/1")

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
        self.assertEqual([p.name for p in output.iterdir()], [IMAGE_NAME])
        self.assertEqual((output / IMAGE_NAME).read_bytes(), self.image.read_bytes())

    def test_publication_retries_preserve_image_digest(self):
        first, second = (Path(self.temp.name) / name for name in ("first", "second"))
        release.prepare(self.root, first)
        (self.root / "build-manifest.json").touch()
        release.prepare(self.root, second)
        self.assertEqual(release.sha256(first / IMAGE_NAME), release.sha256(second / IMAGE_NAME))

    def test_invalid_or_dirty_revision_is_never_published(self):
        for revision in ("SNAPSHOT", "r1-abc-dirty", "../../escape", "r1"):
            self.profile["version_code"] = revision
            self.write_metadata()
            self.checksums()
            with self.assertRaisesRegex(ValueError, "Invalid firmware revision"):
                release.prepare(self.root, Path(self.temp.name) / "invalid")

    def test_notes_show_firmware_revision_build_date_and_source_changes(self):
        manifest = json.loads((self.root / "build-manifest.json").read_text())
        title, notes = release.release_notes(self.root, manifest, "owner/repo", "10")
        self.assertEqual(title, "ubi2-oc_2026.09.18_r36347-e304e64c26")
        self.assertIn("    e304e64c26 Firmware update", notes)
        for removed in ("설치", "Assets", "SHA256SUMS", "추가 패키지", "<details>"):
            self.assertNotIn(removed, notes)
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

    def publication_api(self, fault=None):
        self.calls = []
        self.draft = record(10, draft=True, assets=[])
        def fake_gh(*args):
            self.calls.append(args)
            if args == ("api", "repos/owner/repo/releases/10/assets?per_page=100"):
                return json.dumps(self.draft["assets"])
            if args[:3] == ("api", "--method", "POST"):
                if args[3] == "repos/owner/repo/releases":
                    return json.dumps(self.draft)
                self.assertTrue(args[3].startswith("https://uploads.github.com/repos/owner/repo/releases/10/assets?name="))
                if fault == "upload":
                    raise subprocess.CalledProcessError(1, args)
                path = Path(args[args.index("--input") + 1])
                asset = {"id": len(self.draft["assets"]) + 100, "name": path.name, "state": "uploaded",
                         "size": path.stat().st_size, "digest": "sha256:" + release.sha256(path)}
                if fault == "digest":
                    asset["digest"] = "sha256:" + "0" * 64
                self.draft["assets"].append(asset)
                return json.dumps(asset)
            if args[:3] == ("api", "--method", "PATCH"):
                self.assertEqual(args[3], "repos/owner/repo/releases/10")
                self.assertIn("target_commitish=main", args)
                self.draft["draft"] = False
                return json.dumps(self.draft)
            if args[:3] == ("api", "--method", "DELETE"):
                asset_id = int(args[3].rsplit("/", 1)[1])
                self.draft["assets"] = [a for a in self.draft["assets"] if a["id"] != asset_id]
                return ""
            if args[:2] == ("release", "delete"):
                return ""
            self.fail(f"Unexpected API call (draft tags/list lookups are unavailable): {args}")
        return fake_gh

    def assert_not_published_or_pruned(self):
        self.assertFalse(any(c[:3] == ("api", "--method", "PATCH")
                             or c[:2] == ("release", "delete") for c in self.calls))

    def test_no_release_is_published_or_pruned_after_upload_failure(self):
        with patch.object(release, "releases", return_value=[record(n) for n in range(1, 4)]), \
             patch.object(release, "gh", side_effect=self.publication_api("upload")):
            with self.assertRaises(subprocess.CalledProcessError):
                release.publish(self.root, Path(self.temp.name) / "assets", "owner/repo", "10", "1", COMMIT)
        self.assertTrue(any("draft=true" in c for c in self.calls))
        self.assert_not_published_or_pruned()

    def test_publish_uses_creation_response_when_release_list_is_stale(self):
        # The list omits the new release even after publication. This reproduces
        # the real API failure, as well as the absence of a tag for the draft.
        with patch.object(release, "releases", return_value=[record(n) for n in range(1, 4)]), \
             patch.object(release, "gh", side_effect=self.publication_api()):
            release.publish(self.root, Path(self.temp.name) / "assets", "owner/repo", "10", "1", COMMIT)
        create = self.calls[0]
        self.assertIn("target_commitish=main", create)
        self.assertNotIn(COMMIT, create)
        edit = next(i for i, c in enumerate(self.calls) if c[:3] == ("api", "--method", "PATCH"))
        deletion = next(i for i, c in enumerate(self.calls) if c[:2] == ("release", "delete"))
        self.assertLess(edit, deletion)
        self.assertEqual(self.calls[deletion][2], f"{release.PREFIX}1-1")
        self.assertEqual(len(self.draft["assets"]), 1)

    def test_digest_mismatch_keeps_draft_and_previous_releases(self):
        with patch.object(release, "releases", return_value=[]), \
             patch.object(release, "gh", side_effect=self.publication_api("digest")):
            with self.assertRaisesRegex(RuntimeError, "digest mismatch"):
                release.publish(self.root, Path(self.temp.name) / "assets", "owner/repo", "10", "1", COMMIT)
        self.assert_not_published_or_pruned()

    def test_resume_replaces_only_incomplete_assets_in_existing_draft(self):
        fake_gh = self.publication_api()
        self.draft["assets"] = [{"id": 42, "name": IMAGE_NAME, "state": "uploaded", "size": 1}]
        with patch.object(release, "releases", return_value=[self.draft]), patch.object(release, "gh", side_effect=fake_gh):
            release.publish(self.root, Path(self.temp.name) / "assets", "owner/repo", "10", "1", COMMIT)
        self.assertFalse(any("draft=true" in c for c in self.calls))
        self.assertIn(("api", "--method", "DELETE", "repos/owner/repo/releases/assets/42"), self.calls)
        self.assertTrue(release.complete(self.draft))

    def test_server_failure_removes_starter_and_preserves_verified_uploads(self):
        api = self.publication_api()
        failed = False
        def flaky(*args):
            nonlocal failed
            if args[:3] == ("api", "--method", "POST") and IMAGE_NAME in args[3] and not failed:
                failed = True
                self.calls.append(args)
                self.draft["assets"].append({"id": 42, "name": IMAGE_NAME, "state": "starter", "size": 0})
                raise subprocess.CalledProcessError(1, args, stderr="gh: Error saving asset (HTTP 500)")
            return api(*args)
        with patch.object(release, "releases", return_value=[]), patch.object(release, "gh", side_effect=flaky), \
             patch.object(release.time, "sleep") as sleep:
            release.publish(self.root, Path(self.temp.name) / "assets", "owner/repo", "10", "1", COMMIT)
        sleep.assert_called_once_with(5)
        self.assertIn(("api", "--method", "DELETE", "repos/owner/repo/releases/assets/42"), self.calls)
        uploads = [c for c in self.calls if c[:3] == ("api", "--method", "POST") and "--input" in c]
        self.assertEqual(len(uploads), 2)
        self.assertEqual(len(self.draft["assets"]), 1)
        self.assertTrue(release.complete(self.draft))

    def test_lost_upload_response_reuses_asset_after_verifying_digest(self):
        for fault in ("server", "timeout"):
            with self.subTest(fault=fault):
                api = self.publication_api()
                failed = False
                def flaky(*args):
                    nonlocal failed
                    result = api(*args)
                    if args[:3] == ("api", "--method", "POST") and IMAGE_NAME in args[3] and not failed:
                        failed = True
                        if fault == "timeout":
                            raise subprocess.TimeoutExpired(args, 180)
                        raise subprocess.CalledProcessError(1, args, stderr="HTTP 502")
                    return result
                with patch.object(release, "releases", return_value=[]), patch.object(release, "gh", side_effect=flaky), \
                     patch.object(release.time, "sleep"):
                    release.publish(self.root, Path(self.temp.name) / fault, "owner/repo", "10", "1", COMMIT)
                uploads = [c for c in self.calls if c[:3] == ("api", "--method", "POST") and "--input" in c]
                self.assertEqual(len(uploads), 1)
                self.assertFalse(any(c[:3] == ("api", "--method", "DELETE") for c in self.calls))
                self.assertTrue(release.complete(self.draft))

    def test_persistent_server_errors_and_permission_errors_leave_draft_unpublished(self):
        for status, attempts in ((500, 3), (403, 1)):
            with self.subTest(status=status):
                api = self.publication_api()
                def failing(*args):
                    if args[:3] == ("api", "--method", "POST") and IMAGE_NAME in args[3]:
                        self.calls.append(args)
                        raise subprocess.CalledProcessError(1, args, stderr=f"HTTP {status}")
                    return api(*args)
                with patch.object(release, "releases", return_value=[]), patch.object(release, "gh", side_effect=failing), \
                     patch.object(release.time, "sleep") as sleep:
                    with self.assertRaises(subprocess.CalledProcessError):
                        release.publish(self.root, Path(self.temp.name) / str(status), "owner/repo", "10", "1", COMMIT)
                uploads = [c for c in self.calls if c[:3] == ("api", "--method", "POST") and IMAGE_NAME in c[3]]
                self.assertEqual(len(uploads), attempts)
                self.assertEqual(sleep.call_count, attempts - 1)
                self.assert_not_published_or_pruned()


if __name__ == "__main__":
    unittest.main()
