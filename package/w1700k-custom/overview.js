/* SPDX-License-Identifier: GPL-2.0-only
 * Copyright (C) 2026 openwrt-w1700k-builds contributors
 * GitHub release upgrade interface inspired by w1700k/builds.
 * Replacement implementation: authenticated RPC, checked downloads and no force flash.
 */
'use strict';
'require view';
'require rpc';
'require fs';
'require ui';

const repository = 'ACK72/openwrt-w1700k-builds';
const helper = '/usr/libexec/w1700k-upgrade';
const boardInfo = rpc.declare({ object: 'system', method: 'board' });

function execute(args) {
	return fs.exec(helper, args).then(function(result) {
		if (result.code !== 0)
			throw new Error(result.stderr || _('Firmware operation failed.'));
		return JSON.parse(result.stdout);
	});
}

function pollResult() {
	const deadline = Date.now() + 240000;
	return new Promise(function(resolve, reject) {
		function check() {
			execute(['status']).then(function(result) {
				if (result.status === 'error')
					reject(new Error(result.message));
				else if (result.status !== 'busy')
					resolve(result);
				else if (Date.now() > deadline)
					reject(new Error(_('Operation timed out. Reload this page to check its status.')));
				else
					setTimeout(check, 1000);
			}).catch(reject);
		}
		check();
	});
}

return view.extend({
	load: function() {
		return Promise.all([boardInfo(), execute(['status'])]);
	},

	showError: function(error) {
		ui.showModal(_('Firmware upgrade failed'), [
			E('p', {}, error.message),
			E('div', { 'class': 'right' }, E('button', {
				'class': 'btn', 'click': ui.hideModal
			}, _('Close')))
		]);
	},

	working: function(message) {
		ui.showModal(_('Firmware upgrade'), [E('p', { 'class': 'spinning' }, message)]);
	},

	install: function(image) {
		this.working(_('Rechecking the image before installation…'));
		return execute(['install', image.sha256, image.keep]).then(pollResult).then(result => {
			if (result.status !== 'installing')
				throw new Error(_('Unexpected upgrade status.'));
			this.reconnecting(image.keep);
		}).catch(error => this.showError(error));
	},

	reconnecting: function(keep) {
		this.working(_('Installing firmware. Keep the device powered on until it reconnects.'));
		setTimeout(function() {
			ui.awaitReconnect.apply(ui, keep === 'reset' ? ['192.168.1.1', 'openwrt.lan'] : []);
		}, 10000);
	},

	confirm: function(image) {
		ui.showModal(_('Install verified firmware'), [
			E('p', {}, image.name),
			E('p', {}, _('SHA-256 and device compatibility checks passed.')),
			E('code', { 'style': 'overflow-wrap:anywhere' }, image.sha256),
			E('p', {}, image.keep === 'keep' ? _('Current settings will be kept.') : _('Current settings will be erased.')),
			E('div', { 'class': 'right' }, [
				E('button', { 'class': 'btn', 'click': ui.hideModal }, _('Cancel')),
				' ', E('button', { 'class': 'btn cbi-button-positive',
					'disabled': this.readonly, 'click': ui.createHandlerFn(this, () => this.install(image))
				}, _('Install and reboot'))
			])
		]);
	},

	download: function(release, keep) {
		this.working(_('Downloading firmware and checking its SHA-256 and device compatibility…'));
		return execute(['download', release.tag, keep ? 'keep' : 'reset'])
			.then(pollResult).then(image => {
				if (image.status !== 'ready')
					throw new Error(_('Unexpected download status.'));
				this.confirm(image);
			}).catch(error => this.showError(error));
	},

	selectRelease: function(result) {
		if (result.status !== 'listed' || !Array.isArray(result.releases))
			throw new Error(_('Unexpected release list.'));
		if (!result.releases.length)
			throw new Error(_('No compatible published releases were found.'));
		const select = E('select', { 'class': 'cbi-input-select' }, result.releases.map((release, i) =>
			E('option', { 'value': i }, release.title)));
		const keep = E('input', { 'type': 'checkbox', 'checked': true });
		ui.showModal(_('Available W1700K releases'), [
			E('p', {}, select),
			E('p', {}, E('label', {}, [keep, ' ', _('Keep current settings')])),
			E('p', {}, _('Back up your settings before upgrading.')),
			E('div', { 'class': 'right' }, [
				E('button', { 'class': 'btn', 'click': ui.hideModal }, _('Cancel')),
				' ', E('button', { 'class': 'btn cbi-button-positive', 'disabled': this.readonly,
					'click': ui.createHandlerFn(this, () => this.download(result.releases[Number(select.value)], keep.checked))
				}, _('Download and verify'))
			])
		]);
	},

	check: function() {
		this.working(_('Retrieving releases from GitHub…'));
		return execute(['list']).then(pollResult).then(result => this.selectRelease(result))
			.catch(error => this.showError(error));
	},

	render: function([board, current]) {
		this.readonly = !L.hasViewPermission();
		if (current.status === 'busy') {
			this.working(_('Waiting for the current firmware operation…'));
			pollResult().then(result => {
				if (result.status === 'ready') this.confirm(result);
				else if (result.status === 'listed') this.selectRelease(result);
				else if (result.status === 'installing') this.reconnecting(result.keep);
				else ui.hideModal();
			}).catch(error => this.showError(error));
		} else if (current.status === 'ready') {
			this.confirm(current);
		} else if (current.status === 'installing') {
			this.reconnecting(current.keep);
		}
		return E('div', {}, [
			E('h2', {}, _('W1700K Firmware Upgrade')),
			E('p', {}, (board.release || {}).description || board.model),
			E('p', {}, E('a', { 'href': 'https://github.com/' + repository + '/releases',
				'target': '_blank', 'rel': 'noopener noreferrer' }, repository)),
			E('p', {}, _('Install a published W1700K UBI2 release with its included packages.')),
			E('button', { 'class': 'btn cbi-button-action', 'disabled': this.readonly,
				'click': ui.createHandlerFn(this, this.check) }, _('Check for GitHub firmware'))
		]);
	},

	handleSaveApply: null,
	handleSave: null,
	handleReset: null
});
