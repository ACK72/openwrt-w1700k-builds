import pathlib
import shutil
import subprocess
import unittest

class UpgradeButtons(unittest.TestCase):
    def test_boolean_attributes_preserve_permissions(self):
        node = shutil.which('node')
        self.assertIsNotNone(node, 'Node is required for release UI regression checks')
        subprocess.run([node, str(pathlib.Path(__file__).with_name('upgrade_buttons.cjs'))], check=True)
