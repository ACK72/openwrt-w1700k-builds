"""Ensure installed customizations cannot silently disappear from release images."""
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('customize', ROOT / 'scripts/customize.py')
custom = importlib.util.module_from_spec(spec)
spec.loader.exec_module(custom)


class Customizations(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.view = self.root / 'feeds/luci/applications/luci-app-attendedsysupgrade' / custom.VIEW
        self.view.parent.mkdir(parents=True)
        self.view.write_text('upstream view')
        self.acl = self.root / 'feeds/luci/applications/luci-app-attendedsysupgrade/root/usr/share/rpcd/acl.d/luci-app-attendedsysupgrade.json'
        self.acl.parent.mkdir(parents=True)
        self.acl.write_text(json.dumps({'luci-app-attendedsysupgrade': {
            'read': {'ubus': {'rpc-sys': ['packagelist', 'upgrade_start']}}, 'write': {}}}))

    def install(self):
        with patch.object(custom.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0)):
            custom.apply(self.root)

    def image(self):
        image = self.root / 'build_dir/target-test/root-airoha'
        shutil.copytree(self.root / 'files', image)
        shutil.copyfile(self.acl, image / 'usr/share/rpcd/acl.d/luci-app-attendedsysupgrade.json')
        view = image / 'www/luci-static/resources/view/attendedsysupgrade/overview.js'
        view.parent.mkdir(parents=True)
        shutil.copyfile(self.view, view)
        channel = image / 'www/luci-static/resources/view/status/channel_analysis.js'
        channel.parent.mkdir(parents=True)
        channel.write_text('channelsForRadio scanInterface')
        (image / 'bin').mkdir()
        for command in custom.RUNTIME_COMMANDS:
            (image / 'bin' / command).write_bytes(b'fixture executable')
        return image

    def test_imports_executable_tools_and_license_notices(self):
        self.install()
        image = self.image()
        custom.verify(self.root)
        self.assertIn('--allow-gpio-writes', (image / 'etc/testgpio.sh').read_text())
        self.assertIn('Gilly1970', (image / 'usr/share/licenses/w1700k-custom/NOTICE').read_text())
        acl = json.loads(self.acl.read_text())['luci-app-attendedsysupgrade']
        self.assertNotIn('upgrade_start', acl['read']['ubus']['rpc-sys'])
        self.assertIn('upgrade_start', acl['write']['ubus']['rpc-sys'])

    def test_changed_or_missing_rootfs_customization_blocks_release(self):
        self.install()
        image = self.image()
        (image / 'usr/libexec/w1700k-upgrade').write_text('old download helper')
        with self.assertRaisesRegex(RuntimeError, 'missing or changed'):
            custom.verify(self.root)

    def test_missing_luci_fix_blocks_release(self):
        self.install()
        image = self.image()
        (image / 'www/luci-static/resources/view/status/channel_analysis.js').write_text('old channel view')
        with self.assertRaisesRegex(RuntimeError, 'Single-wiphy'):
            custom.verify(self.root)

    def test_missing_runtime_tool_blocks_release(self):
        self.install()
        image = self.image()
        (image / 'bin/curl').unlink()
        with self.assertRaisesRegex(RuntimeError, 'runtime command missing.*curl'):
            custom.verify(self.root)

    def test_patch_drift_is_fatal_instead_of_silently_ignored(self):
        with patch.object(custom.subprocess, 'run', return_value=subprocess.CompletedProcess([], 1)):
            with self.assertRaisesRegex(RuntimeError, 'no longer applies'):
                custom.apply(self.root)
        self.assertFalse((self.root / 'files').exists())


if __name__ == '__main__':
    unittest.main()
