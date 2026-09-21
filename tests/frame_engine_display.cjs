const fs = require('node:fs'), vm = require('node:vm'), assert = require('node:assert/strict');
const source = fs.readFileSync(__dirname + '/../package/w1700k-custom/root/www/luci-static/resources/tools/w1700k-frame-engine.js', 'utf8');
const api = vm.runInNewContext('(function(){' + source + '})()', { baseclass: { extend: x => x } });
function sample(time, value, boot = 'test-boot') {
  return { schema: 1, boot_id: boot, sample_uptime: time,
    pse_ports: Array.from({length: 10}, (_, port) => ({port, drops: port === 7 ? value : 0})),
    cdm1: {rx_hwf_drop: 0}, cdm2: {rx_hwf_drop: 0} };
}
let count = 0;
function test(name, run) { run(); count++; }
test('first sample establishes baseline', () => {
  const read = api.createTracker(); assert.equal(read(sample(10, 300000)).available, false);
  const next = read(sample(15, 300000)); assert.equal(next.activeDrop, false); assert.equal(next.pseRate, 0);
});
test('observed increment and elapsed time', () => {
  const read = api.createTracker(); read(sample(10, 100)); const next = read(sample(15, 250));
  assert.equal(next.pseDelta, 150); assert.equal(next.pseRate, 30); assert.equal(next.ports[7].rate, 30);
  assert.equal(next.activeDrop, true); assert.match(api.dropText(next, 7), /30.0\/s.*Δ150.*5.0s/);
});
test('error does not zero baseline', () => {
  const read = api.createTracker(); read(sample(10, 4174)); read(sample(15, 4324));
  assert.equal(read({error: 'failed'}).available, false);
  const next = read(sample(25, 4474)); assert.equal(next.pseDelta, 150); assert.equal(next.pseRate, 15);
});
test('long refresh interval does not amplify rate', () => {
  const read = api.createTracker(); read(sample(0, 100));
  assert.equal(read(sample(60, 1900)).pseRate, 30);
});
for (const [name, change] of [
  ['missing ports', x => delete x.pse_ports], ['partial ports', x => x.pse_ports.pop()],
  ['null port', x => x.pse_ports[7] = null],
  ['duplicate port', x => x.pse_ports[8].port = 7], ['null drop', x => x.pse_ports[7].drops = null],
  ['string drop', x => x.pse_ports[7].drops = '120'], ['negative drop', x => x.pse_ports[7].drops = -1],
  ['large raw counter', x => x.pse_ports[7].drops = 0x100000000], ['missing CDM', x => delete x.cdm1],
  ['NaN time', x => x.sample_uptime = NaN], ['null time', x => x.sample_uptime = null],
  ['missing boot', x => delete x.boot_id], ['old API', x => delete x.schema]
]) test(name + ' preserves baseline', () => {
  const read = api.createTracker(); read(sample(10, 100)); const invalid = sample(15, 150); change(invalid);
  assert.equal(read(invalid).available, false);
  assert.equal(read(sample(20, 200)).pseDelta, 100);
});
test('reboot rebaselines even with a larger counter', () => {
  const read = api.createTracker(); read(sample(10, 100)); assert.equal(read(sample(15, 50000, 'new-boot')).available, false);
  assert.equal(read(sample(20, 50010, 'new-boot')).pseDelta, 10);
});
test('reset and wrap rebaseline conservatively', () => {
  const read = api.createTracker(); read(sample(10, 0xfffffffe));
  assert.equal(read(sample(15, 2)).available, false); assert.equal(read(sample(20, 5)).pseDelta, 3);
});
test('a per-port reset cannot be hidden by other increasing ports', () => {
  const read = api.createTracker(); read(sample(10, 100)); const reset = sample(15, 1); reset.pse_ports[1].drops = 1000;
  assert.equal(read(reset).available, false);
});
test('duplicate and delayed samples do not rewind baseline', () => {
  const read = api.createTracker(); read(sample(10, 100)); assert.equal(read(sample(10, 200)).available, false);
  assert.equal(read(sample(9, 1)).available, false); assert.equal(read(sample(20, 300)).pseRate, 20);
});
test('CDM HWF drops are separate from PSE port drops', () => {
  const read = api.createTracker(); read(sample(10, 100)); const fe = sample(15, 100); fe.cdm2.rx_hwf_drop = 10;
  const next = read(fe); assert.equal(next.pseRate, 0); assert.equal(next.cdmRate, 2); assert.equal(next.activeDrop, true);
});
test('missing sample is never healthy', () => {
  const state = api.createTracker()(null); assert.equal(state.available, false); assert.match(api.dropText(state, 7), /N\/A/);
});
console.log(count + ' Frame Engine display cases passed');
