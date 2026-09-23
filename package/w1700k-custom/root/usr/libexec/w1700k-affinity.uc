#!/usr/bin/env ucode
// SPDX-License-Identifier: GPL-2.0-only
// W1700K has purpose-specific rings, not a configured RSS indirection table.
import { glob, readfile, writefile, realpath } from 'fs';

function required(path) {
	let value = readfile(path);
	if (value == null)
		die(`Cannot read ${path}`);
	return trim(value);
}

function task_info(pid) {
	let status = required(`/proc/${pid}/status`);
	let name = match(status, /^Name:\s*([^\n]+)/);
	let cpus = match(status, /\nCpus_allowed_list:\s*([^\n]+)/);
	if (!name || !cpus)
		die(`Incomplete task status for ${pid}`);
	return { name: trim(name[1]), cpus: trim(cpus[1]) };
}

function plan_file(plan, path, value, effective) {
	let old = required(path);
	if (old != value || (effective && required(effective) != value))
		push(plan, { path, value, old, effective });
}

function build_plan(mode, flows) {
	if (required('/tmp/sysinfo/board_name') != 'gemtek,w1700k-ubi')
		die('This policy requires Gemtek W1700K');
	if (required('/sys/devices/system/cpu/online') != '0-3')
		die('The locality policy requires CPUs 0-3 online');

	let plan = [], tasks = [], rings = {}, wifi_phys = {}, wifi_seen = {}, queues = [];
	for (let path in glob('/sys/class/net/*')) {
		let driver = split(realpath(`${path}/device/driver`) ?? '', '/')[-1];
		if (driver != 'airoha_eth' && driver != 'mt7996e')
			continue;
		if (driver == 'mt7996e') {
			let phy = required(`${path}/phy80211/index`);
			wifi_phys[`phy${phy}`] = true;
		}
		for (let queue in glob(`${path}/queues/rx-*/rps_cpus`))
			push(queues, queue);
	}
	if (!length(queues))
		die('No supported receive queues found');

	for (let path in glob('/proc/[0-9]*/status')) {
		let status = readfile(path);
		let m = match(status ?? '', /^Name:\s*([^\n]+)/);
		if (!m)
			continue; // Processes can exit during enumeration.
		let name = trim(m[1]), cpu = null;
		if (match(name, /^napi\/qdma_eth-/))
			die('Anonymous QDMA NAPI: the QDMA identity kernel patch is required');
		m = match(name, /^napi\/qdma([01])-([rt])(\d+)$/);
		if (m) {
			let ring = +m[3];
			if (ring >= (m[2] == 'r' ? 32 : 2) || rings[name])
				die(`Unexpected QDMA ring identity: ${name}`);
			rings[name] = true;
			cpu = +m[1] + 1; // QDMA0/LAN -> CPU1, QDMA1/WAN -> CPU2.
		} else {
			m = match(name, /^napi\/(phy\d+)-\d+$/);
			if (m && wifi_phys[m[1]]) {
				cpu = 3; // Same CPU as the steerable mt76 NPU host RX IRQs.
				wifi_seen[m[1]] = true;
			}
		}
		if (cpu == null)
			continue;
		let pid = match(path, /^\/proc\/(\d+)\/status$/)[1];
		let info = task_info(pid), value = mode == '0' ? '0-3' : `${cpu}`;
		if (info.name != name)
			die(`Task changed during discovery: ${pid}`);
		if (info.cpus != value)
			push(tasks, { pid, name, value, old: info.cpus });
	}
	// Never infer a QDMA ID from enumeration order or PID order.
	if (length(keys(rings)) != 68)
		die('Expected 32 RX and 2 TX completion NAPI contexts on each QDMA');
	for (let phy in keys(wifi_phys))
		if (!wifi_seen[phy])
			die(`Missing NAPI threads for ${phy}`);

	let banks = {}, wifi_irq = 0;
	for (let line in split(required('/proc/interrupts'), '\n')) {
		let m = match(line, /^\s*(\d+):.*\sairoha_eth\.([0-7])$/);
		let cpu, id;
		if (m) {
			id = m[1];
			if (banks[m[2]])
				die('Duplicate Ethernet IRQ bank');
			banks[m[2]] = true;
			cpu = +m[2] < 4 ? 1 : 2;
		} else {
			m = match(line, /^\s*(\d+):.*\smt76-npu\.[01]$/);
			if (m) {
				id = m[1];
				cpu = 3;
			} else {
				m = match(line, /^\s*(\d+):\s*(\d+)\s+(\d+)\s+(\d+)\s+(\d+).*\smt7996e(-hif)?$/);
				if (m) {
					// These MSI children cannot be steered by smp_affinity.
					// Keep their CPU0 path; Wi-Fi NAPI and NPU RX use CPU3.
					if (+m[3] || +m[4] || +m[5])
						die('mt7996 PCIe IRQ delivery is not confined to CPU0');
					wifi_irq++;
				}
				continue;
			}
		}
		plan_file(plan, `/proc/irq/${id}/smp_affinity_list`, mode == '0' ? '0-3' : `${cpu}`,
		          mode == '0' ? null : `/proc/irq/${id}/effective_affinity_list`);
	}
	if (length(keys(banks)) != 8)
		die('Expected all eight QDMA IRQ banks');
	if (length(keys(wifi_phys)) && wifi_irq != 2)
		die('Expected both mt7996 PCIe IRQs');
	for (let task in tasks)
		push(plan, task);

	// Disable both tables in locality mode: RFS may steer even with RPS=0.
	if (mode != '2') {
		for (let path in queues) {
			plan_file(plan, path, '0');
			let flow_path = replace(path, /rps_cpus$/, 'rps_flow_cnt');
			if (readfile(flow_path) != null)
				plan_file(plan, flow_path, '0');
		}
		return plan;
	}

	// Explicit RPS always requires both global and per-queue RFS tables.
	// Round to powers of two to match the kernel allocation/readback behavior.
	if (flows < 16 || flows > 4096)
		die('steering_flows must be between 16 and 4096 in RPS mode');
	let per_queue = 16;
	while (per_queue < flows)
		per_queue *= 2;
	let global = 32768, global_path = '/proc/sys/net/core/rps_sock_flow_entries';
	while (global < per_queue * length(queues))
		global *= 2;
	let previous_global = +required(global_path);
	if (previous_global > global)
		global = previous_global;
	plan_file(plan, global_path, `${global}`);
	for (let path in queues)
		plan_file(plan, replace(path, /rps_cpus$/, 'rps_flow_cnt'), `${per_queue}`);
	for (let path in queues)
		plan_file(plan, path, 'f');
	return plan;
}

function change(item, value) {
	if (item.pid) {
		if (task_info(item.pid).name != item.name)
			die(`NAPI task changed: ${item.pid}`);
		// pid and cpulist are validated numeric strings, never interface names.
		if (system(`taskset -pc ${value} ${item.pid} >/dev/null`) != 0 ||
		    task_info(item.pid).cpus != value)
			die(`Cannot set NAPI affinity for ${item.pid}`);
	} else {
		if (writefile(item.path, value) == null || required(item.path) != value)
			die(`Cannot set ${item.path}`);
		if (item.effective && required(item.effective) != value)
			die(`IRQ effective affinity differs: ${item.effective}`);
	}
}

function apply_plan(plan) {
	let done = [];
	try {
		for (let item in plan) {
			// Include a write that succeeds but fails readback in rollback.
			push(done, item);
			change(item, item.value);
		}
	} catch (err) {
		for (let i = length(done) - 1; i >= 0; i--) {
			try {
				let item = done[i];
				// Restoring an old broad IRQ mask need not yield that effective mask.
				change({ ...item, effective: null }, item.old);
			} catch (rollback) {
				warn(`w1700k-affinity: rollback failed: ${rollback}\n`);
			}
		}
		die(err);
	}
}

// CLI
try {
	let dry = false, mode = '1', flows = 256;
	for (let i = 0; i < length(ARGV); i++) {
		let arg = ARGV[i];
		if (arg == '-n')
			dry = true;
		else if (arg == '-l') {
			if (!match(ARGV[++i] ?? '', /^\d+$/))
				die('Invalid flow table size');
			flows = +ARGV[i];
		} else if (arg == '' || arg == '0' || arg == '1' || arg == '2')
			mode = arg || '1';
		else
			die('Usage: w1700k-affinity.uc [-n] [-l flows] [0|1|2]');
	}
	let plan = build_plan(mode, flows);
	if (dry)
		print(sprintf('%J\n', { mode, policy: 'wifi=3 lan=1 wan=2', changes: plan }));
	else
		apply_plan(plan);
} catch (err) {
	warn(`w1700k-affinity: ${err}\n`);
	exit(1);
}
