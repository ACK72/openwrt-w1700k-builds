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
'require dom';

const repository = '@BUILDER_REPOSITORY@';
const helper = '/usr/libexec/w1700k-upgrade';
const boardInfo = rpc.declare({ object: 'system', method: 'board' });

function releaseBuild(release) {
	const matches = Array.from(String(release.notes || '').matchAll(/<!-- w1700k-build:(.*?) -->/g));
	if (matches.length !== 1) return null;
	try {
		const build = JSON.parse(matches[0][1]);
		if (!/^[0-9]+$/.test(build.run_id) || !/^[0-9]+$/.test(build.build_attempt) ||
			! /^[a-f0-9]{40}$/.test(build.builder_commit) || !/^[a-f0-9]{40}$/.test(build.source)) return null;
		return build;
	} catch (_) { return null; }
}

function buildRelation(installed, release, revision) {
	const candidate = releaseBuild(release);
	if (!candidate) return _('Build identity unavailable');
	if (installed.repository === repository && /^[0-9]+$/.test(installed.run_id || '') &&
		/^[0-9]+$/.test(installed.build_attempt || '')) {
		return ['run_id', 'build_attempt', 'builder_commit', 'source'].every(k => installed[k] === candidate[k])
			? _('Same build as installed') : _('Different build');
	}
	const short = String(revision || '').match(/^r[0-9]+-([a-f0-9]{7,40})$/);
	return short && candidate.source.startsWith(short[1])
		? _('Same source revision; exact build identity unavailable') : _('Build identity unavailable');
}

function timeValue(value) {
	const ms = typeof value === 'string' ? Date.parse(value) : NaN;
	return Number.isFinite(ms) ? ms : null;
}

function elapsedText(milliseconds) {
	const minutes = Math.floor(Math.abs(milliseconds) / 60000);
	if (!minutes) return _('less than a minute');
	const days = Math.floor(minutes / 1440), hours = Math.floor(minutes % 1440 / 60);
	return (days ? days + _('d ') : '') + (hours ? hours + _('h ') : '') + (minutes % 60) + _('m');
}

function publishedText(value) {
	const ms = timeValue(value);
	if (ms === null) return _('Publication time unavailable');
	const delta = Date.now() - ms;
	return new Date(ms).toLocaleString() + ' (' + elapsedText(delta) + ' ' +
		(delta >= 0 ? _('ago') : _('in the future; check the clock')) + ')';
}

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
		return Promise.all([boardInfo(), execute(['status']), execute(['info'])]);
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
			E('p', { 'class': 'alert-message warning', 'style': image.prerelease ? '' : 'display:none' },
				_('You selected an RC image. This is a test release that has not been promoted to stable.')),
			E('p', {}, _('SHA-256 and device compatibility checks passed.')),
			E('code', { 'style': 'overflow-wrap:anywhere' }, image.sha256),
			E('p', {}, image.keep === 'keep' ? _('Current settings will be kept.') : _('Current settings will be erased.')),
			E('div', { 'class': 'right' }, [
				E('button', { 'class': 'btn', 'click': ui.hideModal }, _('Cancel')),
				' ', E('button', { 'class': 'btn cbi-button-positive',
					'disabled': this.readonly || null, 'click': ui.createHandlerFn(this, () => this.install(image))
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
		const releases = result.releases.slice().sort((a, b) => Number(!!a.prerelease) - Number(!!b.prerelease));
		const installed = this.installed || {}, revision = ((this.board || {}).release || {}).revision;
		const details = E('div');
		const updateDetails = release => {
			const published = timeValue(release.published);
			// An RC and its stable promotion share build identity but can have
			// different publication times. Do not guess which release was installed.
			const reference = timeValue(installed.build_started_at);
			const rows = [E('p', {}, buildRelation(installed, release, revision)),
				E('p', {}, _('Published: ') + publishedText(release.published))];
			if (reference !== null && published !== null) {
				const delta = published - reference;
				rows.push(E('p', {}, _('Compared with the installed build start: ') +
					(delta === 0 ? _('same time') : elapsedText(delta) + ' ' + (delta > 0 ? _('later') : _('earlier')))));
			}
			dom.content(details, rows);
		};
		const warning = E('p', { 'class': 'alert-message warning',
			'style': releases[0].prerelease ? '' : 'display:none' },
			_('You selected an RC image. This is a test release that has not been promoted to stable.'));
		const select = E('select', { 'class': 'cbi-input-select', 'change': function() {
			warning.style.display = releases[Number(this.value)].prerelease ? '' : 'none';
			updateDetails(releases[Number(this.value)]);
		} }, releases.map((release, i) =>
			E('option', { 'value': i }, (release.prerelease ? '[RC] ' : '[Stable] ') + release.title)));
		const keep = E('input', { 'type': 'checkbox', 'checked': true });
		updateDetails(releases[0]);
		ui.showModal(_('Available W1700K releases'), [
			E('p', {}, select),
			details,
			warning,
			E('p', {}, E('label', {}, [keep, ' ', _('Keep current settings')])),
			E('p', {}, _('Back up your settings before upgrading.')),
			E('div', { 'class': 'right' }, [
				E('button', { 'class': 'btn', 'click': ui.hideModal }, _('Cancel')),
				' ', E('button', { 'class': 'btn cbi-button-positive', 'disabled': this.readonly || null,
					'click': ui.createHandlerFn(this, () => this.download(releases[Number(select.value)], keep.checked))
				}, _('Download and verify'))
			])
		]);
	},

	check: function() {
		this.working(_('Retrieving releases from GitHub…'));
		return execute(['list']).then(pollResult).then(result => this.selectRelease(result))
			.catch(error => this.showError(error));
	},

	render: function([board, current, installed]) {
		this.board = board;
		this.installed = installed || {};
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
			E('p', {}, _('Installed build: ') + ((installed || {}).run_id ?
				(installed.run_id + ' / ' + installed.build_attempt) : _('Exact identity not recorded by this older image'))),
			E('p', {}, E('a', { 'href': 'https://github.com/' + repository + '/releases',
				'target': '_blank', 'rel': 'noopener noreferrer' }, repository)),
			E('p', {}, _('Install a published W1700K UBI2 release with its included packages.')),
			E('button', { 'class': 'btn cbi-button-action', 'disabled': this.readonly || null,
				'click': ui.createHandlerFn(this, this.check) }, _('Check for GitHub firmware'))
		]);
	},

	handleSaveApply: null,
	handleSave: null,
	handleReset: null
});
