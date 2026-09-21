# Follow-up against ACK72 main a245e96, 2026-09-21

## Version and hardware evidence

Remote main was fetched and confirmed as a245e96 (16:09 KST). Its Actions
run 35571661305 succeeded. The currently installed rollback is builder
3299068, OpenWrt r36432-865ab99cc3, official linux-firmware NPU 20260910.
The earlier experimental 52358c6 full reset failed despite passing NPU stop
handshakes. This follow-up retains 0008/0009/0010 and corrects remaining
failure handling; it is not a claim that the hardware reset now succeeds.

## Latency replies and restoration

The sampler cleared its entire averaging window on a change to raw `ip route
get` output. A real WAN failover therefore reset N/12 to 1/1; a temporary
lookup failure could do the same. A service restart also discarded history.
The latest main still contained this code.

Keep the last 12 router-to-target attempts through route changes, including
lost probes, and retain a validated recent window in tmpfs across short
service restarts. The arithmetic mean, mean absolute deviation (Jitter),
five-second interval and caption stay unchanged. Target changes, reboot,
invalid data and a restart after a long gap intentionally begin a new window.
The route query process is removed, not supplemented with more probes.

Eight tests execute the real averaging program, display and bounded shell
sampler. On the router 12/12 persisted for 70 seconds and through a service
restart; Internet and LuCI RPC remained available. The restored old backup
had left the sampler service disabled in rc.d; the clean-install helper now
reenables it after restore unless the configuration explicitly opts out.

## mwan3 route-state race

In mwan3 3.6.12, a main-table route event can precede installation of the
per-interface default. The monitor reads no default; the later non-main-table
notification is discarded before arming its refresh. ROUTE_STATUS remains
stale until another event or the periodic sweep. At 16:55, this progressed to
a false offline state and conntrack flush even after the Wi-Fi lease returned.

Move the existing debounced refresh before table filtering. A helper accepts
only the reviewed input hash, verifies its output hash, compiles the ucode
before atomic replacement and is idempotent. Unknown versions fail visibly.
It is invoked after the pinned installer and before mwan3 on subsequent boots.
The current router has this fix; WAN forwarding and management were verified.
No wireless reset was needed to apply it.

## Terminal recovery failure

The previous fail-closed path stopped queues but never informed mac80211
that the associated STA was no longer usable. It could leave an apparently
connected wireless WAN after hardware recovery had already failed. Queue
`ieee80211_connection_loss()` only for associated STAs after marking terminal
failure; teardown then runs outside the recovery mutex. Guard subsequent
driver register accesses in that state so teardown/debug reads do not keep
accessing the failed PCIe endpoint. Interrupts are masked before this guard.

DMA reset now returns an error when the hardware revision register reads all
ones before cleanup or immediately after WFSYS reset. Full and L1 recovery
propagate it, balance NAPI without scheduling it on failure, and do not free
tokens, reload firmware or restart queues after that error. These checks are
not proof of DMA-idle and do not replace the NPU handshake. No undocumented
busy bits, PCIe bus reset, GPIO power control or extra reset delay is added.

The original NPU/host DMA quiescence and physical WFSYS/PCIe reset interaction
remain unresolved. The prior failed idle full reset is negative hardware
evidence, not a successful recovery test. Do not inject another full reset on
the live network merely to repeat it.

## 6 GHz reconnects

The rollback also had an unsolicited beacon-loss disconnect at 17:06:39,
recovering association at 17:06:46. This shows the issue predates 0009/0010.
mac80211 already deduplicates repeated beacon-loss probe attempts. Idle
failures with very few outstanding tokens rule out ring starvation as a
complete explanation. Preserve 0010's independently tested starvation fix;
do not relax beacon/probe timeouts to hide the remaining issue.

A different disconnect at 17:14:17 was reason 1 from the upstream AP. The
user confirmed changing that AP's power/settings. Exclude it from automatic
reconnect failures. The remaining beacon RX gap and nullfunc completion path
still require targeted evidence; a root-cause fix is not yet demonstrated.

## Gilly selection

Keep the existing selected fixes and add the small netdev-add steering hook.
The latest f729395 revision's parent-IRQ conversion, wholesale steering,
FlowSense and fan changes are separately assessed in the Gilly follow-up.
No FDK firmware, NPU reservation size or ring capacity is changed.
