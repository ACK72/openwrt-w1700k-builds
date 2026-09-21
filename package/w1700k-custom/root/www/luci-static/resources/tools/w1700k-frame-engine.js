'use strict';
'require baseclass';

// SPDX-License-Identifier: Apache-2.0
function counter(value) {
	return typeof value === 'number' && Number.isSafeInteger(value) && value >= 0;
}

function snapshot(fe) {
	if (!fe || fe.error || fe.schema !== 1 || typeof fe.boot_id !== 'string' || !fe.boot_id ||
	    typeof fe.sample_uptime !== 'number' || !isFinite(fe.sample_uptime) || fe.sample_uptime < 0 ||
	    !Array.isArray(fe.pse_ports) || fe.pse_ports.length !== 10)
		return null;
	var counters = {}, ports = {};
	for (var p of fe.pse_ports) {
		if (!p || !counter(p.port) || p.port > 9 || ports[p.port] || !counter(p.drops) || p.drops > 0xffffffff)
			return null;
		ports[p.port] = true;
		counters['p' + p.port] = p.drops;
	}
	for (var key of ['cdm1', 'cdm2']) {
		var c = fe[key];
		if (!c || !counter(c.rx_hwf_drop) || c.rx_hwf_drop > 0xffffffff)
			return null;
		counters[key] = c.rx_hwf_drop;
	}
	return { boot: fe.boot_id, time: fe.sample_uptime, counters: counters };
}

function createTracker() {
	var previous = null;
	return function(fe) {
		var now = snapshot(fe), result = { available: false, reason: 'Counters unavailable', ports: {}, seconds: null,
			pseDelta: null, cdmHwfDelta: null, pseRate: null, cdmRate: null, activeDrop: false };
		// Failed/partial queries must never replace a valid baseline with zero.
		if (!now) return result;
		result.reason = 'Collecting baseline';
		if (!previous || now.boot !== previous.boot) { previous = now; return result; }
		if (now.time <= previous.time) { result.reason = 'Waiting for a newer sample'; return result; }
		// A decrease can be a reset or a 32-bit wrap. Without a hardware reset
		// generation they are ambiguous: rebaseline instead of inventing drops.
		if (Object.keys(now.counters).some(function(key) { return now.counters[key] < previous.counters[key]; })) {
			previous = now; result.reason = 'Counter reset or wrap'; return result;
		}
		result.available = true;
		result.seconds = now.time - previous.time;
		result.pseDelta = 0;
		for (var i = 0; i < 10; i++) {
			var delta = now.counters['p' + i] - previous.counters['p' + i];
			result.ports[i] = { delta: delta, rate: delta / result.seconds };
			result.pseDelta += delta;
		}
		result.cdmHwfDelta = now.counters.cdm1 - previous.counters.cdm1 + now.counters.cdm2 - previous.counters.cdm2;
		result.pseRate = result.pseDelta / result.seconds;
		result.cdmRate = result.cdmHwfDelta / result.seconds;
		// Observed counter increments, not a diagnosis of shared-buffer exhaustion.
		result.activeDrop = result.pseDelta > 0 || result.cdmHwfDelta > 0;
		previous = now;
		return result;
	};
}

function dropText(state, port) {
	if (!state.available) return 'Drop rate: N/A (' + state.reason + ')';
	var item = port == null ? { delta: state.pseDelta, rate: state.pseRate } : state.ports[port];
	return 'Drop ' + item.rate.toFixed(1) + '/s (Δ' + item.delta + ' / ' + state.seconds.toFixed(1) + 's)';
}

function summary(state) {
	if (!state.available) return state.reason;
	return 'PSE ' + state.pseRate.toFixed(1) + '/s (Δ' + state.pseDelta + ') | CDM HWF ' +
		state.cdmRate.toFixed(1) + '/s (Δ' + state.cdmHwfDelta + ') | ' + state.seconds.toFixed(1) + 's interval';
}

return baseclass.extend({ createTracker: createTracker, dropText: dropText, summary: summary });
