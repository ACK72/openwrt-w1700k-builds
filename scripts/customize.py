#!/usr/bin/env python3
"""Install the release UI, diagnostics and a license-compatible LuCI fix."""
import argparse
import json
import os
import shutil
import subprocess
from pathlib import Path
from repositories import builder_repository

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / 'package/w1700k-custom'
VIEW = 'htdocs/luci-static/resources/view/attendedsysupgrade/overview.js'
RUNTIME_COMMANDS = ('sh', 'ls', 'awk', 'chmod', 'mkdir', 'mv', 'rm', 'rmdir',
                    'jq', 'curl', 'grep', 'sha256sum', 'wc', 'tr', 'df', 'sleep',
                    'ubus', 'uci', 'sysupgrade', 'devmem', 'cat', 'timeout', 'ping', 'ip', 'head', 'date',
                    'mktemp', 'logger', 'ucode', 'taskset')


def rendered(source):
    return source.read_bytes().replace(b'@BUILDER_REPOSITORY@', builder_repository().encode())


def apply(openwrt):
    luci = openwrt / 'feeds/luci'
    attended = luci / 'applications/luci-app-attendedsysupgrade'
    view = attended / VIEW
    if not view.is_file():
        raise RuntimeError('Missing LuCI attended sysupgrade source')
    for patch in sorted((ROOT / 'patches/luci').glob('*.patch')):
        command = ['git', '-C', str(luci), 'apply', '--whitespace=nowarn']
        if subprocess.run([*command, '--check', str(patch)], capture_output=True).returncode == 0:
            subprocess.run([*command, str(patch)], check=True)
        elif subprocess.run([*command, '--reverse', '--check', str(patch)], capture_output=True).returncode:
            raise RuntimeError(f'LuCI patch no longer applies: {patch.name}')
    view.write_bytes(rendered(PACKAGE / 'overview.js'))
    # Keep irqbalance from moving IRQs owned by the platform NAPI policy.
    for patch in sorted((ROOT / 'patches/packages').glob('*.patch')):
        command = ['git', '-C', str(openwrt / 'feeds/packages'), 'apply', '--whitespace=nowarn']
        if subprocess.run([*command, '--check', str(patch)], capture_output=True).returncode == 0:
            subprocess.run([*command, str(patch)], check=True)
        elif subprocess.run([*command, '--reverse', '--check', str(patch)], capture_output=True).returncode:
            raise RuntimeError(f'Packages patch no longer applies: {patch.name}')
    # Keep the upstream dashboard while applying our small presentation fix.
    for patch in sorted((ROOT / 'patches/flowsense').glob('*.patch')):
        command = ['git', '-C', str(openwrt), 'apply', '--whitespace=nowarn']
        if subprocess.run([*command, '--check', str(patch)], capture_output=True).returncode == 0:
            subprocess.run([*command, str(patch)], check=True)
        elif subprocess.run([*command, '--reverse', '--check', str(patch)], capture_output=True).returncode:
            raise RuntimeError(f'FlowSense patch no longer applies: {patch.name}')
    # The stock ASU ACL grants upgrade_start to read-only users. Keep firmware
    # installation in the write scope alongside our authenticated helper.
    acl_path = attended / 'root/usr/share/rpcd/acl.d/luci-app-attendedsysupgrade.json'
    acl = json.loads(acl_path.read_text(encoding='utf-8'))
    scope = acl['luci-app-attendedsysupgrade']
    methods = scope['read'].get('ubus', {}).get('rpc-sys', [])
    scope['read']['ubus']['rpc-sys'] = [method for method in methods if method != 'upgrade_start']
    methods = scope['write'].setdefault('ubus', {}).setdefault('rpc-sys', [])
    if 'upgrade_start' not in methods:
        methods.append('upgrade_start')
    acl_path.write_text(json.dumps(acl, indent=2) + '\n', encoding='utf-8')
    overlay = openwrt / 'files'
    shutil.copytree(PACKAGE / 'root', overlay, dirs_exist_ok=True)
    helper = overlay / 'usr/libexec/w1700k-upgrade'
    helper.write_bytes(rendered(PACKAGE / 'root/usr/libexec/w1700k-upgrade'))
    for script in [*(overlay / 'usr/libexec').rglob('*'),
                   *(overlay / 'etc').glob('*.sh'), *(overlay / 'etc/uci-defaults').glob('*'),
                   *(overlay / 'etc/init.d').glob('*'), *(overlay / 'etc/hotplug.d').glob('*/*')]:
        if not script.is_file():
            continue
        script.chmod(0o755)
    licenses = overlay / 'usr/share/licenses/w1700k-custom'
    licenses.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(PACKAGE / 'NOTICE', licenses / 'NOTICE')
    for license in ('GPL-2.0', 'Apache-2.0'):
        shutil.copyfile(ROOT / 'LICENSES' / license, licenses / license)
    print('Installed authenticated release UI, diagnostics and single-wiphy fix')


def verify(openwrt):
    roots = list((openwrt / 'build_dir').glob('target-*/root-airoha'))
    if len(roots) != 1:
        raise RuntimeError('Expected one compiled Airoha root filesystem')
    root = roots[0]
    if '--policyscript=/usr/libexec/w1700k-irq-policy' not in (root / 'etc/init.d/irqbalance').read_text():
        raise RuntimeError('irqbalance is missing the platform affinity policy')
    for command in RUNTIME_COMMANDS:
        paths = [root / directory / command for directory in ('bin', 'sbin', 'usr/bin', 'usr/sbin')]
        if not any(path.is_file() or path.is_symlink() for path in paths):
            raise RuntimeError(f'Customization runtime command missing from rootfs: {command}')
    for source in (PACKAGE / 'root').rglob('*'):
        if not source.is_file():
            continue
        relative = source.relative_to(PACKAGE / 'root')
        target = root / relative
        if not target.is_file() or rendered(source) != target.read_bytes():
            raise RuntimeError(f'Customization missing or changed in rootfs: {relative}')
        # Windows fixtures have no POSIX executable bits; release builds run on Linux.
        if os.name != 'nt' and (relative.suffix == '.sh' or 'libexec' in relative.parts or 'init.d' in relative.parts or 'hotplug.d' in relative.parts or 'uci-defaults' in relative.parts) and not target.stat().st_mode & 0o111:
            raise RuntimeError(f'Customization is not executable: {relative}')
    view = (root / 'www/luci-static/resources/view/attendedsysupgrade/overview.js').read_text(encoding='utf-8')
    channel = (root / 'www/luci-static/resources/view/status/channel_analysis.js').read_text(encoding='utf-8')
    if builder_repository() not in view or '/usr/libexec/w1700k-upgrade' not in view:
        raise RuntimeError('Release upgrade view is missing from image rootfs')
    identity = root / 'usr/share/w1700k/build.json'
    if not identity.is_file() or identity.read_bytes() != (openwrt / 'files/usr/share/w1700k/build.json').read_bytes():
        raise RuntimeError('Build identity missing or changed in image rootfs')
    flowsense = (root / 'www/luci-static/resources/view/airoha_flowsense/status.js').read_text(encoding='utf-8')
    if 'function latencyState(' not in flowsense or 'cs.latency.detail' not in flowsense:
        raise RuntimeError('FlowSense mean RTT display is missing from rootfs')
    if 'npu-monitor.jitter.enabled' not in (root / 'etc/init.d/npu-jitter').read_text():
        raise RuntimeError('FlowSense sampler opt-out is missing from rootfs')
    backend = (root / 'usr/libexec/rpcd/luci.airoha_flowsense').read_text()
    if not backend.startswith('#!/usr/bin/env ucode') or 'function cpu_sample()' not in backend:
        raise RuntimeError('Isolated FlowSense ucode backend missing from rootfs')
    if (root / 'usr/share/rpcd/ucode/luci.airoha_flowsense.uc').exists():
        raise RuntimeError('Duplicate native FlowSense RPC plugin would conflict')
    if not (root / 'etc/rc.d/S98w1700k-monitor').is_symlink():
        raise RuntimeError('Restore-safe monitor startup missing from rootfs')
    rtmon = root / 'usr/sbin/mwan3rtmon'
    if not rtmon.exists() or 'Refresh before filtering non-main tables' not in rtmon.read_text():
        raise RuntimeError('Patched nft mwan3 missing from image')
    if not (root / 'usr/share/rpcd/ucode/mwan3').exists():
        raise RuntimeError('mwan3 nft RPC plugin missing from image')
    if 'channelsForRadio' not in channel or 'scanInterface' not in channel:
        raise RuntimeError('Single-wiphy fix is missing from image rootfs')
    acl = json.loads((root / 'usr/share/rpcd/acl.d/luci-app-attendedsysupgrade.json').read_text(encoding='utf-8'))
    if 'upgrade_start' in acl['luci-app-attendedsysupgrade']['read'].get('ubus', {}).get('rpc-sys', []):
        raise RuntimeError('Read-only users must not be permitted to start firmware upgrades')
    for name in ('NOTICE', 'GPL-2.0', 'Apache-2.0'):
        if not (root / 'usr/share/licenses/w1700k-custom' / name).is_file():
            raise RuntimeError(f'Customization license missing: {name}')
    print('Verified upgrade UI, executable diagnostics, single-wiphy fix and licenses in rootfs')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=('apply', 'verify'))
    parser.add_argument('openwrt', type=Path)
    args = parser.parse_args()
    globals()[args.operation](args.openwrt.resolve())
