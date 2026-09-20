// SPDX-License-Identifier: GPL-2.0-only
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../package/w1700k-custom/overview.js'), 'utf8');
for (const permission of [true, false, null]) {
  let modal;
  // Match LuCI E(): non-null attributes are serialized, including false.
  const E = (tag, attrs, children) => ({ tag, attrs: Object.fromEntries(Object.entries(attrs || {}).filter(([, v]) => v != null)), children });
  const ctx = { view: { extend: o => o }, rpc: { declare: () => () => Promise.resolve({}) }, fs: {},
    L: { hasViewPermission: () => permission }, _: s => s, E, ui: {
      showModal: (title, nodes) => { modal = nodes; }, hideModal() {}, createHandlerFn: () => () => {}
    } };
  const view = vm.runInNewContext('(function(){' + source + '\n})()', ctx);
  const buttons = root => {
    if (!root) return [];
    if (Array.isArray(root)) return root.flatMap(buttons);
    return root.tag === 'button' ? [root] : buttons(root.children);
  };
  const disabled = node => Object.hasOwn(node.attrs, 'disabled');
  const page = view.render([{ release: {} }, { status: 'idle' }]);
  assert.equal(disabled(buttons(page)[0]), permission !== true, 'Check button permission');
  view.selectRelease({status: 'listed', releases: [{ tag: 'r1', title: 'test', prerelease: true }]});
  assert.equal(disabled(buttons(modal).at(-1)), permission !== true, 'Download button permission');
  view.confirm({name: 'test.itb', keep: 'keep', sha256: '0'.repeat(64)});
  assert.equal(disabled(buttons(modal).at(-1)), permission !== true, 'Install button permission');
}
console.log('All three upgrade buttons respect writable, read-only and denied sessions.');
