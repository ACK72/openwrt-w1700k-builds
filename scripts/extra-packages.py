#!/usr/bin/env python3
"""Install pinned nft-native mwan3 recipes before feed dependency resolution."""
import argparse
import hashlib
import io
import json
import re
import shutil
import subprocess
import tarfile
import time
from pathlib import Path, PurePosixPath
from urllib.error import URLError
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]


def fetch(url):
    # codeload occasionally resets connections; the checksum still decides.
    for attempt in range(3):
        try:
            with urlopen(url, timeout=90) as response:
                return response.read()
        except (URLError, TimeoutError):
            if attempt == 2:
                raise
            time.sleep(5 * 2 ** attempt)


def prepare(openwrt, cache):
    lock = json.loads((ROOT / 'configs/extra-packages.json').read_text())
    cache.mkdir(parents=True, exist_ok=True)
    for item in lock:
        archive = cache / (item['commit'] + '.tar.gz')
        if not archive.exists():
            data = fetch(item['url'])
            if hashlib.sha256(data).hexdigest() != item['sha256']:
                raise RuntimeError('Source archive checksum mismatch: ' + item['repo'])
            archive.write_bytes(data)
        data = archive.read_bytes()
        if hashlib.sha256(data).hexdigest() != item['sha256']:
            raise RuntimeError('Cached source checksum mismatch: ' + item['repo'])
        dest = openwrt / item['destination']
        # Replace only the two explicitly selected feed recipes in this checkout.
        if dest.is_symlink() or not dest.resolve().is_relative_to((openwrt / 'feeds').resolve()):
            raise RuntimeError('Unexpected feed recipe path')
        files = {}
        with tarfile.open(fileobj=io.BytesIO(data)) as tf:
            for member in tf:
                name = PurePosixPath(member.name)
                if name.is_absolute() or '..' in name.parts or member.issym() or member.islnk():
                    raise RuntimeError('Unsafe source archive member')
                parts = name.parts[1:]
                if member.isfile() and parts and parts[0] in ('Makefile', 'files', 'src', 'root', 'htdocs', 'po'):
                    files[Path(*parts)] = tf.extractfile(member).read()
        if Path('Makefile') not in files:
            raise RuntimeError('Source recipe missing')
        if dest.exists():
            shutil.rmtree(dest)
        for relative, content in files.items():
            path = dest / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        recipe = dest / 'Makefile'
        # Anchor the release bump; a plain substring would also rewrite :=10.
        content = re.sub(r'(?m)^PKG_RELEASE:=1$', 'PKG_RELEASE:=2', recipe.read_text())
        # Avoid a wall-clock-dependent LuCI package version.
        content = content.replace('PKG_SRC_PREFIX:=$(shell date +%y).999', 'PKG_SRC_PREFIX:=26.999')
        recipe.write_text(content)
        if item['repo'] == 'dl12345/mwan3':
            subprocess.run(['git', 'apply', '--unsafe-paths', '-p1', '--directory=files',
                            str(ROOT / 'patches/mwan3/0001-refresh-route-state-before-filter.patch')], cwd=dest, check=True)
        print('Installed', item['repo'], item['commit'])
    (openwrt.parent / 'extra-packages.json').write_text(json.dumps(lock, indent=2) + '\n')


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('openwrt', type=Path)
    p.add_argument('cache', type=Path)
    a = p.parse_args()
    prepare(a.openwrt.resolve(), a.cache.resolve())
