"""Exercise the actual helper filter, including OpenWrt's regex-free jq build."""
import copy
import json
import pathlib
import shutil
import subprocess
import unittest

HELPER = pathlib.Path(__file__).resolve().parents[1] / 'package/w1700k-custom/root/usr/libexec/w1700k-upgrade'
FILTER = HELPER.read_text().split('jq -ce --arg repo "$REPOSITORY" --argjson max "$MAX_SIZE" \'\n', 1)[1].split("'\n}", 1)[0]
REPO = 'ACK72/openwrt-w1700k-builds'

def release(rc=True, number='123', published='2026-09-21T00:00:00Z'):
    channel = 'w1700k-oc-rc' if rc else 'w1700k-oc'
    tag = f'{channel}-{number}-1'
    name = f'openwrt-airoha-an7581-gemtek_w1700k-ubi-squashfs-sysupgrade-{channel}-r36432.itb'
    return dict(draft=False, prerelease=rc, tag_name=tag, name=tag, published_at=published,
                assets=[dict(state='uploaded', name=name, size=22000000,
                             digest='sha256:'+'ab'*32,
                             browser_download_url=f'https://github.com/{REPO}/releases/download/{tag}/{name}')])

class ReleaseFilter(unittest.TestCase):
    def setUp(self):
        if not shutil.which('jq'):
            self.skipTest('jq is required; the same cases also run against the router jq')

    def filter(self, rows):
        result = subprocess.run(['jq', '-ce', '--arg', 'repo', REPO, '--argjson', 'max', '134217728', FILTER],
                                input=json.dumps(rows), text=True, capture_output=True, check=True)
        return json.loads(result.stdout)

    def test_latest_stable_and_rc(self):
        result = self.filter([release(), release(False), release(number='122', published='2026-09-20T00:00:00Z')])
        self.assertEqual([r['tag'] for r in result], ['w1700k-oc-123-1','w1700k-oc-rc-123-1'])

    def test_invalid_metadata_is_never_offered(self):
        cases = [('draft',True), ('prerelease',False), ('tag_name','w1700k-oc-rc-../123-1'),
                 ('tag_name','w1700k-oc-rc-123-'), ('tag_name','w1700k-oc-rc-１２３-1'),
                 ('tag_name','w1700k-oc-rc-123-1\n'), ('tag_name',None)]
        assets = [('state','new'), ('size',0), ('size',134217729), ('size',1.5), ('size','22000000'),
                  ('digest','sha256:'+'A'*64), ('digest','sha256:'+'a'*63), ('digest',None),
                  ('browser_download_url','https://example.invalid/image.itb'),
                  ('name',release()['assets'][0]['name'].replace('r36432','r')),
                  ('name',release()['assets'][0]['name']+'\n')]
        for field, value in cases:
            with self.subTest(field=field, value=value):
                row=release();row[field]=value
                self.assertEqual(self.filter([row]), [])
        for field, value in assets:
            with self.subTest(asset_field=field, value=value):
                row=release();row['assets'][0][field]=value
                self.assertEqual(self.filter([row]), [])
        row=release();row['assets'].append(copy.deepcopy(row['assets'][0]))
        self.assertEqual(self.filter([row]), [])

    def test_empty_release_list(self):
        self.assertEqual(self.filter([]), [])
