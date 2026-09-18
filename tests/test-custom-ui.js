// SPDX-License-Identifier: GPL-2.0-only
// Verify the actual LuCI module contracts without a router or browser globals.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const root = path.resolve(__dirname, '..');

function load(source, file, permission = true) {
    const rpcCalls = [], modals = [];
    const rpc = { declare: spec => device => {
        rpcCalls.push([spec.method, device]);
        return Promise.resolve(spec.method === 'scan' ? [] : {});
    }};
    const ui = {
        showModal: (title, body) => modals.push({ title, body }),
        hideModal() {}, createHandlerFn: (context, fn) => fn.bind(context), awaitReconnect() {}
    };
    const E = (tag, attrs, children) => ({ tag, attrs, children });
    const view = new Function('view', 'rpc', 'fs', 'ui', 'L', 'E', '_', 'setTimeout', source)(
        { extend: value => value }, rpc, file, ui, { hasViewPermission: () => permission }, E,
        value => value, callback => callback());
    return { view, rpcCalls, modals };
}

async function main() {
    const source = fs.readFileSync(path.join(root, 'package/w1700k-custom/overview.js'), 'utf8');
    const calls = [];
    let responses = [];
    const file = { exec: async (command, args) => {
        assert.equal(command, '/usr/libexec/w1700k-upgrade');
        calls.push(args);
        return { code: 0, stdout: JSON.stringify(responses.shift()) };
    }};
    const { view } = load(source, file);
    let confirmed = null, error = null, reconnect = null;
    view.confirm = image => { confirmed = image; };
    view.showError = value => { error = value; };
    view.reconnecting = keep => { reconnect = keep; };
    responses = [{ status: 'busy' }, { status: 'ready', sha256: 'a'.repeat(64), keep: 'keep' }];
    await view.download({ tag: 'w1700k-ubi2-oc-123-1' }, true);
    assert.equal(confirmed.status, 'ready');
    assert.deepEqual(calls.map(call => call[0]), ['download', 'status']);
    responses = [{ status: 'busy' }, { status: 'installing' }];
    await view.install(confirmed);
    assert.equal(reconnect, 'keep');
    assert.equal(calls[2][0], 'install');
    confirmed = null;
    responses = [{ status: 'busy' }, { status: 'error', message: 'Checksum mismatch' }];
    await view.download({ tag: 'w1700k-ubi2-oc-123-1' }, false);
    assert.equal(confirmed, null);
    assert.equal(error.message, 'Checksum mismatch');
    const readonly = load(source, file, false);
    readonly.view.render([{ release: { description: 'W1700K' } }, { status: 'idle' }]);
    assert.equal(readonly.view.readonly, true);
    readonly.view.confirm({ name: 'firmware.itb', sha256: 'a'.repeat(64), keep: 'reset' });
    const buttons = readonly.modals[0].body.at(-1).children;
    assert.equal(buttons.at(-1).attrs.disabled, true);
    const acl = JSON.parse(fs.readFileSync(path.join(root, 'package/w1700k-custom/root/usr/share/rpcd/acl.d/w1700k-upgrade.json')));
    const scope = acl['luci-app-attendedsysupgrade'];
    assert.deepEqual(Object.keys(scope.read.file), ['/usr/libexec/w1700k-upgrade status']);
    assert.ok(Object.keys(scope.write.file).every(command => !command.includes('_worker')));
    console.log('PASS: authenticated helper contract, confirmation, failure handling and read-only UI');

    if (process.argv[2]) {
        const channel = load(fs.readFileSync(process.argv[2], 'utf8'), {});
        let current = [{ getIfname: () => 'phy0.1-sta0', isUp: () => false },
                       { getIfname: () => 'phy0.1-ap0', isUp: () => true }];
        const device = { getWifiNetworks: async () => current, getName: () => 'radio1', get: () => '5g' };
        await channel.view.readRadio(device);
        assert.deepEqual(channel.rpcCalls.slice(-2), [['scan', 'phy0.1-ap0'], ['info', 'phy0.1-ap0']]);
        current = [{ getIfname: () => 'phy0.1-ap1', isUp: () => true }];
        await channel.view.readRadio(device);
        assert.deepEqual(channel.rpcCalls.slice(-2), [['scan', 'phy0.1-ap1'], ['info', 'phy0.1-ap1']]);
        current = [];
        await channel.view.readRadio(device);
        assert.deepEqual(channel.rpcCalls.slice(-2), [['scan', 'radio1'], ['info', 'radio1']]);
        const channels = [{ band: 2, channel: 1 }, { band: 5, channel: 36 }, { band: 6, channel: 1 }];
        for (const [band, expected] of [['2g', 2], ['5g', 5], ['6g', 6]]) {
            assert.deepEqual(channel.view.channelsForRadio({ get: () => band }, channels), channels.filter(c => c.band === expected));
        }
        assert.deepEqual(channel.view.channelsForRadio({ get: () => undefined }, channels), channels);
        console.log('PASS: actual patched LuCI uses the active interface and filters shared-wiphy bands');
    }
}
main().catch(error => { console.error(error); process.exitCode = 1; });
