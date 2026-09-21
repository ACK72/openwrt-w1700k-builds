# Review of a245e96 / pending-frame priority, 2026-09-21

The findings below describe the original a245e96/aab7c92 implementation.
The [implemented correction](pending-priority-fix-20260921.md) replaces that
unbounded prepass with bounded, rotating admission and adds broader tests.
Its software tests pass; hardware throughput and reconnect acceptance are
still separate requirements.

## Conclusion

Patch `0010-wifi-service-pending-frames-before-data.patch` improves one
secondary-radio starvation case, but is not ready to be treated as a general
fairness fix. It can give pending payload traffic all available descriptors
before normal mac80211 TXQs run. Its fixed PHY order also leaves secondary
radio starvation possible when an earlier PHY has a large pending backlog.

These are scheduling risks reproduced in a software boundary model, **not
evidence that this patch caused the observed PCIe errors or live reconnects**.
Those failures were observed on images without 0010. No new device flash or
wireless reconfiguration was performed for this review. Production code and
the already-dispatched aab7c92 build were not changed during the review.

## Scope and source evidence

Reviewed builder commit `a245e96f80a8b802cb4eef9f7a20ad64012f4a16` and its
unchanged 0010 content in `aab7c920bfe6f3af5d5be3a764f8f0938edfb452`.
The functional change adds an all-PHY pending pass before the original worker
body. The original per-PHY `schedule_all()` calls remain, including their own
pending calls. It does not alter pending helper locks, DMA ownership, ring
sizes, queue stop thresholds, firmware commands or PCIe registers.

Relevant source locations in the selected mt76 / backports source:

- `tx.c:363`, `mt76_tx()`: frames from the direct TX callback are appended to
  `tx_pending` or `tx_offchannel` without a management-only type filter.
- mac80211 `tx.c:1299`, `ieee80211_get_txq()`: TXQ-bypass paths include
  SEND_AFTER_DTIM and PS_RESPONSE frames, and frames for a station that is not
  yet uploaded. Some such traffic can contain payload. Which bypass paths a
  particular MT7996 configuration uses depends on its hardware buffering
  callbacks; this is not a claim that every power-save response uses pending.
- mt76 `tx.c:682`, `mt76_txq_schedule_pending_wcid()`: drains until the list
  is empty, the ring is stopped/blocked/near full, or the PHY is in RESET.
  There is no per-invocation packet/airtime budget. It calls
  `__mt76_tx_queue_skb(..., NULL)` for the stop argument. The normal data
  scheduler's non-AQL pacing is not an additional bound on this helper.
  This helper behavior predates 0010; 0010 changes when it gets descriptors.
- `mt7996/init.c:774`: with NPU active, band 2 aliases band 1's TX queues.
  PSD and data queue IDs therefore do not provide independent ring capacity.
- 0010's new loop checks that a PHY exists and is not the main PHY. It does
  not restrict the change to PHYs sharing the main PHY's `ieee80211_hw`.

## Findings

### 1. Pending payload can displace normal TXQs

The new pass drains the pending list before the normal scheduler without
distinguishing connection-monitor frames from payload or limiting the work.
When a secondary PHY's pending backlog consumes each batch of free
descriptors, normal TXQs receive none until that backlog subsides. This can
increase application latency and change airtime fairness. It is not proof
that aggregate throughput becomes zero: in the reproduced case the device
still submits frames, but they all come from pending traffic.

The previous description of this as giving only "control frames" priority
was too strong. The previous test modeled only one pending frame and did not
cover competing pending payload.

### 2. The fixed order does not protect every secondary radio

The order is always main PHY, then `dev->phys[]` order. On the W1700K NPU
layout, a band-1 pending backlog can consume the band-1/band-2 shared ring
before the band-2 pending pass. In the expanded test a waiting band-2 probe
still receives zero opportunities across ten worker passes. This is a
remaining limitation of the fix, not a newly introduced failure relative
to the original worker in that same test.

A packet cap alone is insufficient if the available descriptors are fewer
than that cap and the starting PHY is always the same. A fair design must
also handle nearly-full shared rings and sustained backlogs.

### 3. Extra work and scope are broader than needed

The prepass is followed by the original pending calls. With three PHYs and
`dev->phys[0]` aliasing the main PHY, pending helper calls rise from four to
seven per worker invocation. Empty lists return quickly; this is **not a
measurement of CPU usage**, nor evidence of a 75% CPU increase. Non-empty
blocked lists require repeated traversal and locking, so the overhead can
be greater than an empty check under congestion or RESET.

The change also affects separate-hw PHY layouts in the common mt76 worker.
That wider scope is unnecessary for the stated shared-hw problem.

## Expanded software audit

The audit compiled the before/after worker and `schedule_all()` bodies from
the actual patch, plus the unchanged real `mt76_txq_stopped()` and
`mt76_txq_schedule_pending_wcid()` bodies. skb storage, locks, DMA completion,
mac80211 data scheduling and the one-WCID-per-PHY dispatcher were mocks.
It therefore checks admission/order and existing stop guards; it cannot
validate concurrent locking, hardware timing, RF, firmware or live throughput.

Except for the last row, ten passes each expose eight usable shared-ring
descriptors. The background band-1 regular-data TXQ remains eligible.

| Pending traffic | Before 0010 | With 0010 |
| --- | --- | --- |
| One band-2 probe | Probe 0, regular data 80 | Probe 1, regular data 79 |
| 80 band-1 payload frames plus one band-2 probe | Pending 0, probe 0, regular data 80 | Pending payload 80, probe 0, regular data 0 |
| 80 band-2 payload frames | Pending 0, regular data 80 | Pending payload 80, regular data 0 |
| 80 band-1 control frames plus one band-2 probe | Band-2 probe 0 | Band-1 pending 80, band-2 probe 0 |
| 400 band-2 payload frames, 480 free descriptors, one pass | Regular data 480 | Pending payload 400 in one helper call, regular data 80 |

RESET, offchannel normal traffic and a full ring remained blocked. An
offchannel probe remained eligible and benefited from the new ordering.
Twenty before/after scenario executions and their audit assertions passed.
The 400-frame row demonstrates absence of a small drain budget, not a
measured 400-frame burst on the router.

Reproduction files are local under `.validation/review-pending-priority/`:
`run.py`, `harness.c`, `results.json`. Run the Python script from the workspace
with the selected source snapshot and the local C compiler available.

## Recovery and observed failures

The pending helper still tests `MT76_RESET` before dequeuing. The channel
change path parks the same worker; full recovery sets RESET on all PHYs and
parks that worker before DMA reclamation. 0010 adds no mutex or new lock
nesting inside those helpers. Source review found no direct bypass of these
guards introduced by 0010. This is not a proof that all reset races are safe.

A long pending drain can delay normal scheduling and completion of a worker
park request. The unbudgeted helper already existed, so an actual timing
regression would require measurement; it must not be called a demonstrated
deadlock or a proven explanation for a channel-command timeout.

The fresh rollback image `3299068`, which lacks 0010, logged another
beacon-loss/reason-4 reconnect around 17:35 on 2026-09-21. Earlier full-reset
PCIe failures also preceded 0010. Removing only this patch therefore cannot
be presented as a fix for all observed failures.

## Recommendation

Do not accept 0010 unchanged as a validated stable fix. Keep the independent
recovery, Latency and mwan3 corrections separate from this experiment.
For a stable comparison image, omit this scheduling experiment; for a revised
candidate, establish all of the following before hardware acceptance:

1. Scope priority handling to the shared-hw/shared-ring case.
2. Use bounded pending work with fair service across PHYs/WCIDs and preserve
   regular-data progress even when only a few descriptors become available.
3. Preserve FIFO/security ordering of payload, EAPOL and management traffic;
   do not blindly extract arbitrary frames from the middle of a pending list.
4. Avoid duplicate pending traversals in the worker while preserving the
   exported helper behavior used by channel changes and reset callers.
5. Test payload and control backlogs on both bands, completion during drain,
   nearly-full rings, RESET and offchannel transitions. Then compare real
   throughput, latency, CPU cost and probe TX/ACK deadlines with/without the
   patch, using the same clean-install and restored configuration procedure.

No guessed packet quota, larger ring, disabled offload, relaxed beacon-loss
timeout, or unverified hardware reset is introduced by this review.
