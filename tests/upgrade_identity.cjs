// SPDX-License-Identifier: GPL-2.0-only
const fs = require('node:fs'), vm = require('node:vm'), assert = require('node:assert/strict');
const source = fs.readFileSync(require('node:path').join(__dirname, '../package/w1700k-custom/overview.js'), 'utf8')
  .replaceAll('@BUILDER_REPOSITORY@', 'ACK72/openwrt-w1700k-builds');
const {releaseBuild, buildRelation, elapsedText, publishedText} = vm.runInNewContext('(function(){' + source.split('function execute(')[0] +
  'return {releaseBuild, buildRelation, elapsedText, publishedText};})()', {rpc: {declare() {}}, _: s => s});
const build = {run_id:'123', build_attempt:'1', builder_commit:'a'.repeat(40), source:'b'.repeat(40)};
const release = {notes:'<!-- w1700k-build:' + JSON.stringify(build) + ' -->'};
const installed = {...build, repository:'ACK72/openwrt-w1700k-builds'};
assert.equal(buildRelation(installed, release), 'Same build as installed');
assert.equal(buildRelation({...installed, build_attempt:'2'}, release), 'Different build');
assert.equal(buildRelation({...installed, repository:'another/repo'}, release), 'Build identity unavailable');
assert.equal(buildRelation({}, release, 'r36432-'+ 'b'.repeat(10)), 'Same source revision; exact build identity unavailable');
assert.equal(buildRelation({}, release, 'r36432-'+ 'c'.repeat(10)), 'Build identity unavailable');
assert.equal(releaseBuild({notes: release.notes+release.notes}), null);
assert.equal(releaseBuild({notes: '<!-- w1700k-build:{not json} -->'}), null);
assert.equal(releaseBuild({notes: '<!-- w1700k-build:'+JSON.stringify({...build, run_id:'invalid'})+' -->'}), null);
assert.equal(publishedText(null), 'Publication time unavailable');
assert.equal(publishedText('invalid'), 'Publication time unavailable');
assert.equal(elapsedText(90061000), '1d 1h 1m');
assert.equal(elapsedText(-60000), '1m');
console.log('Release identity, legacy fallback, ambiguous metadata and time handling passed.');
