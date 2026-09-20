# Channel changes, NPU recovery and PCIe faults

This is a source review, not an additional kernel patch import. The audited
builder is `32990682db2d5baa6f8efbc8b8a86ad5ef0ef25e`, OpenWrt source
`865ab99cc35b85f2bbb949a55016b2c45fe4da88`, mt76 source
`01367e60db433534ad0aa3d3b6c886de8cb7d44c` with the selected patch stack.
The mac80211 reference is backports 7.2, rather than Linux 6.18's in-tree
mac80211. Line numbers below refer to the locally prepared mt76 source.

## Initiating failure versus unsuccessful recovery

The observed sequence was repeated 6GHz AP reconfiguration/ACS, successful ACS
selection, failure to apply beacon/channel settings, MCU command `001a0034`
timeout, PCIe Completion Timeout, and repeated unsuccessful full resets.
This was not the earlier RX page-pool panic. It does not establish which
component first stopped responding: Wi-Fi firmware, PCIe access, or their
interaction during reconfiguration.

`mt7996/mcu.c:4580`, `mt7996_mcu_set_chan_info()`, sends both
`UNI_CHANNEL_SWITCH` and `UNI_CHANNEL_RX_PATH` using the same command ID 0x34.
The timeout message alone cannot identify the failed TLV. Add bounded tracing
of tag, band, control/center channel, width, switch reason, scan/ROC state,
sequence, duration and return code before assigning blame to a specific step.
In `mt7996_mcu_parse_response()` a timeout itself schedules full reset; it does
not require a firmware watchdog assertion. Absence of a watchdog coredump is
therefore not evidence that no firmware problem occurred.

## Confirmed recovery gaps

1. **Scan completion is suppressed during reset.** `scan.c:7-44` clears the
   driver's scan object but skips `ieee80211_scan_completed()` when
   `MT76_MCU_RESET` is set. Full reset sets this bit before `mt76_abort_scan()`.
   The mac80211 scan bit can consequently remain set. Backports 7.2
   `net/mac80211/main.c:488` explicitly warns if restart begins with that bit
   set. Its `scan.c:540` completion callback only schedules software completion;
   it is not a channel-programming MCU command. Keep the guard against restoring
   RF settings while the MCU is down, but deliver the aborted completion exactly
   once. Verify completion work ordering before `ieee80211_restart_hw()`.
   `mt76_scan_work()` also ignores channel-change errors; abort that scan on
   error instead of probing or scheduling another channel. Audit the analogous
   suppressed ROC-expired callback in `channel.c:339` and cancel each PHY's ROC
   work in full reset as the L1 path does.

2. **Full reset lacks NPU lifecycle parity.** `mt7996/mac.c:2150` restarts WED,
   but has no NPU stop/reinitialization and lacks the L1 path's exclusions for
   NPU-owned RRO/TX-free queues. `mt7996_dma_reset()` cleans ring entries before
   its later NPU IRQ disable; disabling interrupts is not proof that NPU DMA
   has stopped. The NPU may still own/access descriptors being reclaimed.
   Gilly 047 addresses three of these omissions but ignores the stop result.
   The L1 path also ignores stop and NPU reinitialization failures.

3. **Failure is allowed to resume traffic.** `mt7996_mac_full_reset():2322`
   holds the device mutex over ten restart attempts. It still wakes queues and
   calls mac80211 restart if all ten fail. `mt7996_mac_restart()` clears reset
   flags and reenables the TX worker on error, and its caller restores normal
   recovery state unconditionally. This explains prolonged survey/RPC lock
   waits and repeated failures. Introduce a bounded terminal failure state,
   preserve quiescence after failure, and propagate recovery errors. Do not
   merely shorten MCU readiness timeouts or hide the warning.

4. **No PCIe AER recovery callbacks.** Neither PCI driver in
   `mt7996/pci.c:242-254` provides `err_handler`. This agrees with the observed
   `no error_detected callback` message. Linux explicitly documents that the
   affected device will not be recovered through AER without these callbacks.
   A WFSYS reset is not equivalent to reinitializing the PCIe functions.
   [Linux AER documentation](https://docs.kernel.org/PCI/pcieaer-howto.html).

The scan defect explains a secondary warning and the NPU/error-state gaps
explain unsuccessful recovery. None alone proves the cause of the first
Completion Timeout. A non-fatal transaction error is also not proof of an
electrically disconnected link or a faulty physical board.

## Safe implementation order

1. Add the channel/recovery trace points and fix scan/ROC completion/error
   propagation. Avoid high-frequency per-packet logging.
2. Adapt Gilly 047 with checked NPU stop and checked ring handoff for both L1
   and full reset. The existing stock-facing stop contract in
   `mt7996/npu.c:594` is SET index 4, GET index 3 until zero, then SET index 6.
   A mailbox response is not the same as the subsequent idle indication.
   Never reclaim DMA-owned memory after an unsuccessful stop. The stop helper
   takes the device mutex itself, so do not call it with that mutex held.
3. Unify success/failure handling, work cancellation and queue ownership.
   Keep management queries responsive using bounded failure responses or an
   isolated query worker, without accessing reset hardware. This contains a
   fault; it does not substitute for hardware recovery.
4. Add coordinated AER recovery for the primary and secondary PCIe functions:
   serialize against driver reset, stop/quiesce NPU and host DMA, request the
   appropriate PCI reset, restore configuration/interrupts and rebuild firmware
   and ring state, then resume only on success. A sysfs `reset_method` listing
   of `flr bus` alone does not validate this sequence.
5. Validate repeated channel changes and AP disable/enable, scan/ROC aborts,
   L1/full-reset fault paths including NPU stop failure, and management access
   during recovery. Test both PCI functions and cold/warm boots. Ordinary
   throughput testing does not exercise all these paths.

These changes primarily affect control/error paths. Preserve the existing
zero-copy/page-pool packet path and offload. No evidence currently justifies a
permanent rate cap, ring-size increase or blanket offload disable. PCIe ASPM is
already disabled by the driver on both functions; disabling it again is not a
new remedy. A non-OC/PCIe-generation comparison is a controlled diagnostic, not
an established fix.

## 6GHz STA reconnects during/after 5GHz tests

The recurring event is beacon loss followed by locally generated reason 4,
then a short association comeback delay (status 30) and reconnection. Similar
events occurred well after the throughput and deliberately forced reconnect
stages ended. Treat load correlation as unproven; do not classify all events
as MCU reset or as an upstream AP-initiated deauthentication. Route-monitor
and DHCP teardown messages follow the loss of the Wi-Fi link.

The effective driver enables `CONNECTION_MONITOR` and `BEACON_FILTER`.
`mac80211.c:2316-2377` updates a per-link timestamp from received matching
beacons and reports loss after seven beacon intervals, with checks from the
periodic MAC worker. It skips monitoring while that PHY is off-channel and
refreshes the timestamp when returning. The diagnostic target is therefore
the driver's received-beacon timestamp and the subsequent null-function/probe
TX status, not just mac80211's default beacon timer. Do not suppress beacon
loss notifications or arbitrarily increase the threshold as a first fix.

`mt7996/init.c:773-780` aliases band 2's TX queues to band 1's on an NPU-active
MT7996. The bands also share MCU/device resources. This provides a possible
cross-band congestion path, but not proof that beacons use that TX queue or
that it caused the recorded event. Capture beacon RX gaps, null/probe enqueue
and completion latency, off-channel state, NPU queue occupancy and upstream
AP events on the same time axis. Compare idle, 5GHz TX and 5GHz RX while
keeping the 6GHz STA and upstream AP configuration fixed. Only change queue
policy or filtering after determining where those frames are delayed/lost.

A successful LAN-to-6GHz-AP load test does not validate the inverse 6GHz
STA/WWAN role. Reports of older acceptance runs must also distinguish kernel
stability checks from uninterrupted STA connectivity.

## Additional shared resource to instrument

A focused replay of all 68 patches affecting `airoha_eth.c`, `airoha_regs.h`,
`airoha_ppe.c` and `airoha_npu.c` onto Linux stable 6.18.52 confirms that the
effective NPU mailbox uses `regmap_read_poll_timeout_atomic(..., 100, 500000)`
under `spin_lock_bh(&core->lock)`. An earlier patch's one-second timeout is
overridden later; it is not the effective value. The same core-0 mailbox serves
PPE and Wi-Fi control messages. If responses stall, a call can spin for about
500 ms while bottom halves are disabled on the caller CPU; waiting callers can
also contend for this lock. This is a conditional latency/congestion mechanism,
not measured proof that such a stall occurred during beacon loss.

Record per-command duration and timeout counters at a bounded rate. A sleepable
control worker can be considered for callers that permit sleeping, with proper
ordering against existing atomic PPE callers. Simply replacing this spinlock
with a mutex or extending the busy-wait timeout is unsafe. Stock NPU idle polling
also consists of multiple mailbox calls, so ten 10–15 ms sleeps do not bound
the whole stop operation to 100–150 ms.

See [Gilly compatibility review](gilly-followup-20260921.md) for parsing,
statistics, PPE and DMA changes that should be considered separately.
