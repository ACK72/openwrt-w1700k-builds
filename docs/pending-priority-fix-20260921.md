# Bounded shared-radio pending scheduling, 2026-09-21

## Behavior

The original 0010 prepass drained every pending list before normal TXQs.
Since pending lists can contain payload, one backlogged radio could consume
the shared ring and displace both regular data and another radio's probe.
The revised patch changes admission only for PHYs sharing one ieee80211_hw.

- Each PHY may dequeue at most 32 pending frames per worker invocation,
  combined across the before-data and after-data phases.
- Each hardware ring initially gives pending traffic at most half of its
  currently usable descriptors, capped at 32. Queue aliases share this
  budget. The existing 32-descriptor free threshold is still excluded from
  usable capacity; this is not a ring-size or hardware-credit change.
- When one slot is available, a per-ring record of the last successful
  pending admission lets regular data go next. A successful regular-data
  burst clears that record. Empty worker wakeups and traffic on other rings
  cannot consume this turn.
- After the regular scheduler runs, pending lists deferred by this admission
  budget may use space that regular data did not use. Both phases share the
  same per-PHY work budget, so the fallback cannot become an unlimited drain.
- The next starting PHY follows the last serviced PHY. Unvisited WCIDs are
  placed ahead of a partly drained WCID for the next pass. A blocked fallback
  preserves that order instead of undoing the rotation.
- Budget exhaustion explicitly reschedules remaining work. Full, blocked,
  RESET or offchannel queues that make no progress do not self-reschedule.
  This prevents a lost wakeup without polling a stalled device.

Frames remain FIFO within each pending queue. The existing offchannel-first
policy, queue-stop checks, RESET guard and locking order are preserved. The
exported pending drain retains its original behavior for channel changes,
reset callers and legacy devices with separate ieee80211_hw instances.

## Performance considerations

Normal data-only traffic takes a fast path: no ring-budget initialization,
pending-list traversal or cursor calculation. The shared data scheduler runs
once instead of repeating it through the main-PHY alias. Its existing AQL,
non-AQL, burst limits and hardware completion path are retained.

The admission record is cleared once on the first successful packet of a
regular data burst, rather than adding work to its inner per-packet loop.
The budget applies to pending work per invocation, not bytes per second.
Queued work is rescheduled, and unused data capacity can be reclaimed by
pending traffic. Offload remains enabled and hardware ring sizes are unchanged.

The value 32 reuses MT_TXQ_FREE_THR as a bounded work quantum. It is not a
measured optimum or an NPU capacity limit. Real throughput/CPU comparison is
still required before claiming that performance is unchanged on the router.

## Verification

`test_tx_fairness.py` compiles the actual before/after pending helpers, WCID
list handling, data-burst and worker functions. Hardware completion,
mac80211 TXQ selection and concurrency entry points are boundary mocks.

- A single band-2 probe gets one of 80 opportunities, leaving 79 for data.
- With sustained pending payload, the congested eight-slot model keeps all
  80 opportunities used and at least 40 available to regular data. Both
  secondary radios make progress.
- With one free slot per completion, 18 opportunities divide into nine
  regular and nine pending frames, with both radios served. The result is
  unchanged by empty wakeups or a busy independent ring.
- When regular data is absent, AQL-blocked or rejected at enqueue, pending
  traffic uses all available capacity in the tested eight-slot cases.
- A 400-frame pending backlog drains over 13 bounded invocations, including
  a case with completions arriving during the drain. No frame is stranded
  waiting for an unrelated new packet to wake the worker.
- Tests cover competing WCIDs, FIFO, enqueue while a WCID is temporarily
  detached, missing PHYs, full/blocked rings, RESET and offchannel traffic.
  Legacy separate-hw and single-PHY results match the original worker.
- A direct exported drain still processes its 400-frame test in one call,
  preserving the channel/reset API's behavior.

The software model checks lock balance/list integrity but does not simulate
all real concurrency interleavings or DMA ordering. It does not establish
that PCIe failures, missed beacons or live reconnects have been fixed.

The complete outer/nested patch stack replays against the selected source;
mt76 package release is incremented from 8 to 9 to distinguish this change.
Local verification ran 47 tests: 44 passed and three release-filter tests
were skipped because jq is not installed on the Windows host. All 12 new
fairness tests passed. The firmware workflow runs the same suite with jq.
Hardware acceptance should compare clean installations with the same saved
configuration: 5 GHz load with a 6 GHz STA, bidirectional AP throughput,
CPU/latency, and normal channel/reconfiguration cycles. Follow the repository's
required no-preservation / mwan3-install / backup-restore procedure.
