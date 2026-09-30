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
const cardStyle = 'display:flex;gap:.75em;align-items:flex-start;margin:.5em 0;padding:.6em .8em;' +
	'border:1px solid;border-radius:6px;cursor:pointer';
const cardBorder = 'var(--border-color-medium,#bbb)';
const selectedBorder = 'var(--primary-color-high,#0069d6)';

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

function revisionOf(text) {
	// Titles join fields with '_' (a word character), so \b cannot anchor here.
	const match = String(text || '').match(/(?:^|[^a-z0-9])r([0-9]+)-([a-f0-9]{7,40})(?![a-z0-9])/);
	return match ? { number: Number(match[1]), hash: match[2], text: 'r' + match[1] + '-' + match[2] } : null;
}

/* Workflow run IDs only grow, and a stable promotion keeps its RC's run, so
 * they order builds exactly. Images without a recorded identity fall back to
 * the OpenWrt revision number, which cannot tell rebuilds of one source apart.
 */
function relation(installed, release, revision) {
	const candidate = releaseBuild(release);
	if (candidate && installed.repository === repository && /^[0-9]+$/.test(installed.run_id || '') &&
		/^[0-9]+$/.test(installed.build_attempt || '')) {
		if (['run_id', 'build_attempt', 'builder_commit', 'source'].every(k => installed[k] === candidate[k]))
			return 'installed';
		const order = Number(candidate.run_id) - Number(installed.run_id) ||
			Number(candidate.build_attempt) - Number(installed.build_attempt);
		return order > 0 ? 'newer' : order < 0 ? 'older' : 'different';
	}
	const current = revisionOf(revision), offered = revisionOf(release.title);
	if (!current || !offered) return 'unknown';
	if (offered.number === current.number)
		return offered.hash.startsWith(current.hash) || current.hash.startsWith(offered.hash) ? 'same-source' : 'different';
	return offered.number > current.number ? 'newer' : 'older';
}

const relationBadges = {
	'installed': ['notice', _('Installed')],
	'same-source': ['notice', _('Same source as installed')],
	'newer': ['important', _('Newer')],
	'older': ['', _('Older')],
	'different': ['', _('Different build')]
};

function badge(kind, text) {
	return E('span', { 'class': 'label' + (kind ? ' ' + kind : '') }, text);
}

function channelBadge(release) {
	return release.prerelease ? badge('warning', _('RC')) : badge('success', _('Stable'));
}

function timeValue(value) {
	const ms = typeof value === 'string' ? Date.parse(value) : NaN;
	return Number.isFinite(ms) ? ms : null;
}

function relativeText(ms) {
	const delta = Date.now() - ms, minutes = Math.round(Math.abs(delta) / 60000);
	let text;
	if (minutes < 1) return _('just now');
	if (minutes < 60) text = _('%d min').format(minutes);
	else if (minutes < 2880) text = _('%d h').format(Math.round(minutes / 60));
	else text = _('%d days').format(Math.round(minutes / 1440));
	return delta >= 0 ? _('%s ago').format(text) : _('%s in the future; check the clock').format(text);
}

function dateText(value) {
	const ms = timeValue(value);
	return ms === null ? _('unknown') : new Date(ms).toLocaleString(undefined,
		{ 'dateStyle': 'medium', 'timeStyle': 'short' }) + ' (' + relativeText(ms) + ')';
}

function sizeText(bytes) {
	return Number.isFinite(bytes) ? (bytes / 1048576).toFixed(1) + ' MiB' : _('unknown');
}

// Commit lines are indented in the release notes; markers are HTML comments.
// LuCI's jsmin only recognises a regex after an operator such as '=' and
// strips literal spaces from anything else, so keep this one out of arrows.
const changeLine = /^\x20{4}([0-9a-f]{7,40})\x20(\S.*)$/;

function changes(release) {
	return String(release.notes || '').split('\n')
		.map(line => changeLine.exec(line))
		.filter(Boolean);
}

function changeList(release) {
	const items = changes(release);
	if (!items.length) return E('p', { 'style': 'opacity:.75' }, _('No change list was published for this release.'));
	return E('details', {}, [
		E('summary', { 'style': 'cursor:pointer' }, _('Recent source changes (%d)').format(items.length)),
		E('ul', { 'style': 'margin:.4em 0 0 1.2em' }, items.map(([, hash, subject]) =>
			E('li', {}, [E('code', {}, hash.substring(0, 10)), ' ', subject])))
	]);
}

function row(title, value) {
	return E('tr', { 'class': 'tr' }, [
		E('td', { 'class': 'td left', 'style': 'width:33%;white-space:nowrap' }, E('strong', {}, title)),
		E('td', { 'class': 'td left', 'style': 'overflow-wrap:anywhere' }, value)
	]);
}

function buttons(children) {
	return E('div', { 'class': 'right', 'style': 'margin-top:1em' }, children);
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

	showError: function(title, error) {
		ui.showModal(title, [
			E('div', { 'class': 'alert-message error' }, error.message),
			buttons(E('button', { 'class': 'btn', 'click': ui.hideModal }, _('Close')))
		]);
	},

	working: function(title, message) {
		ui.showModal(title, [E('p', { 'class': 'spinning' }, message)]);
	},

	install: function(image) {
		this.working(_('Installing firmware'), _('Checking the downloaded image once more…'));
		return execute(['install', image.sha256, image.keep]).then(pollResult).then(result => {
			if (result.status !== 'installing')
				throw new Error(_('Unexpected upgrade status.'));
			this.reconnecting(image.keep);
		}).catch(error => this.showError(_('Installation failed'), error));
	},

	reconnecting: function(keep) {
		this.working(_('Installing firmware'), keep === 'reset'
			? _('Writing the firmware and erasing settings. Keep the device powered on; it will be reachable at 192.168.1.1.')
			: _('Writing the firmware. Keep the device powered on until this page reconnects.'));
		setTimeout(function() {
			ui.awaitReconnect.apply(ui, keep === 'reset' ? ['192.168.1.1', 'openwrt.lan'] : []);
		}, 10000);
	},

	confirm: function(image) {
		const erase = image.keep !== 'keep';
		ui.showModal(_('Ready to install'), [
			E('div', { 'class': 'alert-message success' },
				_('Download verified: the SHA-256 matches the release and the image is compatible with this device.')),
			E('table', { 'class': 'table' }, [
				row(_('Release'), [channelBadge(image), ' ', (revisionOf(image.title) || {}).text || image.title || image.tag]),
				row(_('Published'), dateText(image.published)),
				row(_('Image'), [image.name, E('br'), E('small', {}, sizeText(image.size))]),
				row(_('SHA-256'), E('code', { 'style': 'overflow-wrap:anywhere;font-size:85%' }, image.sha256)),
				row(_('Settings'), erase ? E('strong', {}, _('Erase and restore defaults')) : _('Keep'))
			]),
			image.prerelease ? E('div', { 'class': 'alert-message warning' },
				_('This is an RC build: a test release that has not been promoted to stable.')) : '',
			erase ? E('div', { 'class': 'alert-message error' },
				_('All settings will be erased. The router restarts with default settings at 192.168.1.1.')) : '',
			E('p', {}, _('The router reboots after installation; this takes a few minutes.')),
			buttons([
				E('button', { 'class': 'btn', 'click': ui.hideModal }, _('Cancel')),
				' ', E('button', { 'class': 'btn ' + (erase ? 'cbi-button-negative' : 'cbi-button-positive'),
					'disabled': this.readonly || null, 'click': ui.createHandlerFn(this, () => this.install(image))
				}, _('Install and reboot'))
			])
		]);
	},

	download: function(release, keep) {
		this.working(_('Downloading firmware'),
			_('Downloading the image and checking its SHA-256 and device compatibility…'));
		return execute(['download', release.tag, keep ? 'keep' : 'reset'])
			.then(pollResult).then(image => {
				if (image.status !== 'ready')
					throw new Error(_('Unexpected download status.'));
				this.confirm(image);
			}).catch(error => this.showError(_('Download or verification failed'), error));
	},

	selectRelease: function(result) {
		if (result.status !== 'listed' || !Array.isArray(result.releases))
			throw new Error(_('Unexpected release list.'));
		if (!result.releases.length)
			throw new Error(_('No compatible published releases were found.'));
		const installed = this.installed || {}, revision = ((this.board || {}).release || {}).revision;
		const releases = result.releases.slice().sort((a, b) => Number(!!a.prerelease) - Number(!!b.prerelease));
		const states = releases.map(release => relation(installed, release, revision));
		// Never preselect a downgrade: prefer a newer build, then the installed one.
		let selected = states.indexOf('newer');
		if (selected < 0) selected = states.findIndex(state => state === 'installed' || state === 'same-source');
		if (selected < 0) selected = 0;

		const notice = E('div');
		const keep = E('input', { 'type': 'checkbox' });
		const eraseWarning = E('div', { 'class': 'alert-message error', 'style': 'display:none' },
			_('All settings will be erased. The router restarts with default settings at 192.168.1.1.'));
		keep.checked = true;
		keep.addEventListener('change', () => eraseWarning.style.display = keep.checked ? 'none' : '');

		const cards = releases.map((release, i) => {
			const input = E('input', { 'type': 'radio', 'name': 'w1700k-release', 'style': 'margin-top:.3em' });
			const status = relationBadges[states[i]];
			input.checked = i === selected;
			input.addEventListener('change', () => select(i));
			return E('label', { 'style': cardStyle }, [
				input,
				E('div', { 'style': 'flex:1;min-width:0' }, [
					E('div', { 'style': 'display:flex;flex-wrap:wrap;align-items:center;gap:.25em' }, [
						E('strong', { 'style': 'margin-right:.25em' }, (revisionOf(release.title) || {}).text || release.title),
						channelBadge(release), status ? badge(status[0], status[1]) : ''
					]),
					E('div', { 'style': 'opacity:.8;margin:.2em 0' }, _('Published %s').format(dateText(release.published))),
					changeList(release)
				])
			]);
		});

		function select(index) {
			selected = index;
			cards.forEach((card, i) => {
				card.style.borderColor = i === index ? selectedBorder : cardBorder;
				card.style.boxShadow = i === index ? '0 0 0 1px ' + selectedBorder : 'none';
			});
			const release = releases[index], state = states[index], messages = [];
			if (state === 'installed' || state === 'same-source')
				messages.push(E('div', { 'class': 'alert-message info' },
					_('This build is already installed. Installing it again reflashes the same firmware.')));
			else if (state === 'older')
				messages.push(E('div', { 'class': 'alert-message warning' },
					_('This release is older than the installed firmware. Installing it is a downgrade.')));
			if (release.prerelease)
				messages.push(E('div', { 'class': 'alert-message warning' },
					_('RC builds are test releases that have not been promoted to stable.')));
			dom.content(notice, messages);
		}
		select(selected);

		ui.showModal(_('Available firmware'), [
			E('p', {}, _('Choose a release. Nothing is installed until the image is downloaded, verified and confirmed.')),
			E('div', {}, cards),
			notice,
			E('p', { 'style': 'margin-top:1em' }, E('label', {}, [keep, ' ', _('Keep current settings')])),
			eraseWarning,
			E('p', {}, [
				_('Settings are kept across upgrades, but a backup is recommended.'), ' ',
				E('a', { 'href': L.url('admin/system/flash') }, _('Create a backup'))
			]),
			buttons([
				E('button', { 'class': 'btn', 'click': ui.hideModal }, _('Cancel')),
				' ', E('button', { 'class': 'btn cbi-button-positive', 'disabled': this.readonly || null,
					'click': ui.createHandlerFn(this, () => this.download(releases[selected], keep.checked))
				}, _('Download and verify'))
			])
		]);
	},

	check: function() {
		this.working(_('Checking for firmware'), _('Retrieving the published releases from GitHub…'));
		return execute(['list']).then(pollResult).then(result => this.selectRelease(result))
			.catch(error => this.showError(_('Could not check for firmware'), error));
	},

	render: function([board, current, installed]) {
		this.board = board;
		this.installed = installed || {};
		this.readonly = !L.hasViewPermission();
		if (current.status === 'busy') {
			this.working(_('Firmware operation in progress'), _('Waiting for the current firmware operation…'));
			pollResult().then(result => {
				if (result.status === 'ready') this.confirm(result);
				else if (result.status === 'listed') this.selectRelease(result);
				else if (result.status === 'installing') this.reconnecting(result.keep);
				else ui.hideModal();
			}).catch(error => this.showError(_('Firmware operation failed'), error));
		} else if (current.status === 'ready') {
			this.confirm(current);
		} else if (current.status === 'installing') {
			this.reconnecting(current.keep);
		}
		const release = board.release || {}, identity = this.installed;
		const recorded = /^[0-9]+$/.test(identity.run_id || '') && identity.repository === repository;
		return E('div', {}, [
			E('h2', {}, _('W1700K Firmware Upgrade')),
			E('p', {}, _('Install a published stable or RC release of this firmware. Each image is downloaded, checked against its release SHA-256 and this device, and only installed after you confirm.')),
			E('div', { 'class': 'cbi-section' }, [
				E('h3', {}, _('Installed firmware')),
				E('table', { 'class': 'table' }, [
					row(_('Version'), release.description || release.revision || board.model),
					row(_('Build'), recorded ? E('a', {
						'href': 'https://github.com/' + repository + '/actions/runs/' + identity.run_id,
						'target': '_blank', 'rel': 'noopener noreferrer'
					}, _('Run %s, attempt %s').format(identity.run_id, identity.build_attempt || '1'))
						: _('Not recorded by this image')),
					row(_('Built'), recorded ? dateText(identity.build_started_at) : _('unknown')),
					row(_('Releases'), E('a', { 'href': 'https://github.com/' + repository + '/releases',
						'target': '_blank', 'rel': 'noopener noreferrer' }, repository))
				])
			]),
			this.readonly ? E('div', { 'class': 'alert-message warning' },
				_('Your account has read-only access. Firmware upgrades require write permission.')) : '',
			E('button', { 'class': 'btn cbi-button-action', 'disabled': this.readonly || null,
				'click': ui.createHandlerFn(this, this.check) }, _('Check for GitHub firmware'))
		]);
	},

	handleSaveApply: null,
	handleSave: null,
	handleReset: null
});
