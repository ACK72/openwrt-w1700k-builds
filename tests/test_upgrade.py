"""Exercise release selection, tamper rejection and flash gating with fake hardware."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / 'package/w1700k-custom/root/usr/libexec/w1700k-upgrade'
TAG = 'w1700k-ubi2-oc-123-1'
NAME = 'openwrt-airoha-an7581-gemtek_w1700k-ubi-squashfs-sysupgrade-r123.itb'


@unittest.skipUnless(shutil.which('bash') and shutil.which('jq'), 'requires bash and jq')
class Upgrade(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.state = self.root / 'state'
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        self.data = b'fake firmware payload for validation tests'
        self.digest = hashlib.sha256(self.data).hexdigest()
        (self.root / 'image').write_bytes(self.data)
        self.release = {
            'tag_name': TAG, 'name': 'ubi2-oc_r123', 'draft': False, 'prerelease': False,
            'published_at': '2026-09-18T00:00:00Z',
            'assets': [{'name': NAME, 'size': len(self.data), 'digest': 'sha256:' + self.digest,
                        'browser_download_url': f'https://github.com/ACK72/openwrt-w1700k-builds/releases/download/{TAG}/{NAME}'}],
        }
        self.metadata(self.release)
        self.script('curl', '''out=
while [ "$#" -gt 0 ]; do
    case "$1" in --output) out=$2; shift;; esac
    url=$1
    shift
done
[ "${FAIL_DOWNLOAD:-0}" != 1 ] || exit 22
case "$url" in
  *api.github.com*) cp "$FIXTURE/metadata" "$out";;
  *) cp "$FIXTURE/image" "$out";;
esac
''')
        self.script('ubus', '''printf '{"board_name":"%s","release":{"target":"airoha/an7581"}}' "${BOARD:-gemtek,w1700k-ubi}"
''')
        self.script('uci', '''printf '%s' "${COMPAT:-2.0}"
''')
        self.script('sysupgrade', '''case " $* " in
  *' --test '*) echo "$*" >> "$FIXTURE/validated"; exit "${INVALID_IMAGE:-0}";;
  *) echo "$*" >> "$FIXTURE/flashed";;
esac
''')
        self.script('sleep', 'exit 0\n')
        self.script('stat', 'echo 0\n')
        text = HELPER.read_text().replace("STATE_DIR='/tmp/w1700k-upgrade'", f"STATE_DIR='{self.state.as_posix()}'")
        # Git Bash prepends its system tools when importing a Windows PATH.
        # Resolve the mock directory inside the shell so no real curl is used.
        text = text.replace('set -eu', f'set -eu\nexport PATH="$(cd \'{self.bin.as_posix()}\' && pwd):$PATH"', 1)
        text = text.replace('/sbin/sysupgrade', (self.bin / 'sysupgrade').as_posix())
        self.helper = self.root / 'upgrade'
        self.helper.write_text(text, newline='\n')
        self.helper.chmod(0o755)
        self.env = {**os.environ, 'PATH': str(self.bin) + os.pathsep + os.environ['PATH'], 'FIXTURE': self.root.as_posix()}

    def metadata(self, value):
        (self.root / 'metadata').write_text(json.dumps(value))

    def script(self, name, body):
        path = self.bin / name
        path.write_text('#!/bin/sh\nset -eu\n' + body, newline='\n')
        path.chmod(0o755)

    def run_worker(self, operation, *args):
        (self.state / 'lock').mkdir(parents=True, exist_ok=True)
        result = subprocess.run(['bash', str(self.helper), '_worker', operation, *args],
                                env=self.env, text=True, capture_output=True, timeout=10)
        state = json.loads((self.state / 'state.json').read_text()) if (self.state / 'state.json').exists() else {}
        return result, state

    def test_download_verifies_then_requires_explicit_install(self):
        result, state = self.run_worker('download', TAG, 'keep')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(state['status'], 'ready')
        self.assertFalse((self.root / 'flashed').exists())
        result, state = self.run_worker('install', self.digest, 'keep')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(state['status'], 'installing')
        self.assertNotIn('--force', (self.root / 'flashed').read_text())

    def test_tampered_download_and_changed_image_cannot_flash(self):
        (self.root / 'image').write_bytes(b'corrupt download')
        result, state = self.run_worker('download', TAG, 'keep')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(state['status'], 'error')
        (self.root / 'image').write_bytes(self.data)
        self.assertEqual(self.run_worker('download', TAG, 'keep')[0].returncode, 0)
        (self.state / 'firmware.itb').write_bytes(b'changed after verification')
        result, state = self.run_worker('install', self.digest, 'keep')
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.root / 'flashed').exists())

    def test_incompatible_device_and_incompatible_image_are_rejected(self):
        for environment in ({'BOARD': 'another,device'}, {'COMPAT': '1.0'}, {'INVALID_IMAGE': '1'}):
            with self.subTest(environment=environment):
                original = self.env.copy()
                self.env.update(environment)
                result, state = self.run_worker('download', TAG, 'keep')
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(state['status'], 'error')
                self.env = original
        self.assertFalse((self.root / 'flashed').exists())

    def test_drafts_missing_hash_foreign_urls_and_wrong_assets_are_excluded(self):
        bad = json.loads(json.dumps(self.release))
        bad['assets'][0]['browser_download_url'] = 'https://example.invalid/firmware.itb'
        draft = {**self.release, 'draft': True}
        prerelease = {**self.release, 'prerelease': True}
        missing = json.loads(json.dumps(self.release))
        missing['assets'][0]['digest'] = None
        wrong = json.loads(json.dumps(self.release))
        wrong['assets'][0]['name'] = 'another-device.itb'
        self.metadata([bad, draft, prerelease, missing, wrong, self.release])
        result, state = self.run_worker('list')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual([r['tag'] for r in state['releases']], [TAG])

    def test_keep_mode_cannot_change_after_validation(self):
        self.assertEqual(self.run_worker('download', TAG, 'keep')[0].returncode, 0)
        self.assertNotEqual(self.run_worker('install', self.digest, 'reset')[0].returncode, 0)
        self.assertFalse((self.root / 'flashed').exists())

    def test_reset_is_validated_and_installed_without_force(self):
        self.assertEqual(self.run_worker('download', TAG, 'reset')[0].returncode, 0)
        self.assertEqual(self.run_worker('install', self.digest, 'reset')[0].returncode, 0)
        self.assertTrue((self.root / 'flashed').read_text().startswith('-n '))
        self.assertNotIn('--force', (self.root / 'flashed').read_text())

    def test_public_entry_point_rejects_bad_tags_before_network_access(self):
        result = subprocess.run(['bash', str(self.helper), 'download', '../../wrong;echo', 'keep'],
                                env=self.env, capture_output=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.state / 'release.json').exists())

    def test_network_failure_is_reported_and_lock_released(self):
        self.env['FAIL_DOWNLOAD'] = '1'
        result, state = self.run_worker('download', TAG, 'keep')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(state['status'], 'error')
        self.assertFalse((self.state / 'lock').exists())

    def test_public_list_starts_background_work_and_returns_promptly(self):
        self.metadata([self.release])
        result = subprocess.run(['bash', str(self.helper), 'list'], env=self.env,
                                text=True, capture_output=True, timeout=3)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['status'], 'busy')
        deadline = time.monotonic() + 5
        while (self.state / 'lock').exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        self.assertFalse((self.state / 'lock').exists())
        self.assertEqual(json.loads((self.state / 'state.json').read_text())['status'], 'listed')

    def test_concurrent_operation_is_rejected(self):
        (self.state / 'lock').mkdir(parents=True)
        result = subprocess.run(['bash', str(self.helper), 'list'], env=self.env,
                                text=True, capture_output=True, timeout=3)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('already running', result.stderr)


if __name__ == '__main__':
    unittest.main()
