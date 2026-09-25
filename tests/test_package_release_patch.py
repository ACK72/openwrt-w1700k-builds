"""Apply the package release patch at the current upstream/vendor boundary."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
PATCH = ROOT / 'patches/w1700k/0004-package-bump-mt76-and-hostapd-releases-after-backpor.patch'


class PackageReleasePatch(unittest.TestCase):
    def test_current_hostapd_release_keeps_upstream_changes(self):
        # Upstream 18a969c47580 bumped hostapd to 3 and retained the parallel
        # variants change. A fresh composer has no historical local patch blobs.
        recipes = {
            'package/kernel/mt76/Makefile': (
                'include $(TOPDIR)/rules.mk\n\nPKG_NAME:=mt76\nPKG_RELEASE=1\n\n'
                'PKG_LICENSE:=BSD-3-Clause-Clear\nPKG_LICENSE_FILES:=\n'),
            'package/network/services/hostapd/Makefile': (
                '# SPDX-License-Identifier: GPL-2.0-only\n#\n'
                '# Copyright (C) 2006-2021 OpenWrt.org\n\n'
                'include $(TOPDIR)/rules.mk\n\nPKG_NAME:=hostapd\nPKG_RELEASE:=3\n\n'
                'PKG_SOURCE_URL:=https://w1.fi/hostap.git\nPKG_SOURCE_PROTO:=git\n'
                'PKG_SOURCE_VERSION:=831364bf02710ad09c2f27d3efa92abeeb5634c0\n'
                'PKG_PARALLEL_VARIANTS:=1\n'),
        }
        with tempfile.TemporaryDirectory(prefix='w1700k-release-patch-') as folder:
            root = Path(folder)
            env = {**os.environ, 'GIT_CONFIG_NOSYSTEM': '1',
                   'GIT_CONFIG_GLOBAL': os.devnull}

            def git(*args):
                result = subprocess.run(['git', '-C', folder, *args],
                                        capture_output=True, text=True, env=env)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                return result.stdout.strip()

            git('init')
            git('config', 'user.name', 'Release patch test')
            git('config', 'user.email', 'test@example.invalid')
            git('config', 'core.autocrlf', 'false')
            for name, content in recipes.items():
                path = root / name
                path.parent.mkdir(parents=True)
                path.write_text(content, encoding='utf-8', newline='\n')
            git('add', '.')
            git('commit', '-m', 'Current upstream and vendor package recipes')
            git('am', '--3way', '--committer-date-is-author-date', str(PATCH))
            for name, content in recipes.items():
                expected = (content.replace('PKG_RELEASE=1', 'PKG_RELEASE=2')
                            if 'mt76' in name else
                            content.replace('PKG_RELEASE:=3', 'PKG_RELEASE:=4'))
                self.assertEqual((root / name).read_text(encoding='utf-8'), expected)
            self.assertEqual(git('status', '--porcelain'), '')
            self.assertEqual(git('show', '-s', '--format=%an <%ae>'),
                             'ACK72 <acikom72@gmail.com>')
