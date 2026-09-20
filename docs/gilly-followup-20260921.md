# Gilly follow-up review, 2026-09-21

`origin/main` was fetched again from Gilly1970/Gemtek-W1700K-6.18. Its HEAD
remains `0aa0666de1366b69d5d73d98c19809affc1f76ed`, the revision used in
[the earlier selection](gilly-selection.md). There are no new main-branch
commits since that review. Patch numbers below refer to its `openwrt-patches`.
This is a recommendation list, not an additional kernel patch import.

## Highest-value next changes

| Change | Current ACK72 evidence | Recommendation |
| --- | --- | --- |
| 026 ALL_STA_INFO bounds | Effective `mt7996/mcu.c` still trusts `sta_num`, and handles `UNI_ALL_STA_TXRX_AIR_TIME` in addition to Gilly's three tags | Port the length/count checks with the AIR_TIME element size included. Test truncated headers, oversized counts and all four valid events. Gilly's original default-return would silently discard airtime reports. |
| 044 IE-countdown TLV bounds | Effective parser reads a TLV payload before checking that its complete length is present | Port the bounds checks, adding a check for the MCU/event header before reading `hdr->band`. The Gilly patch only hardens the subsequent TLV loop. This is defensive parsing, not evidence that a malformed event caused the observed PCIe timeout. |
| 949 PPE error propagation | Backport 099-08 declares outer `err = 0` and then shadows it inside the SRAM-flush loop | Remove the inner declaration so commit failures propagate to the caller. Check that no later source update has already fixed the function before applying. This is an initialization/error-path fix with no normal packet-path cost. |
| 047 full-reset NPU lifecycle | A new real failure followed a 6GHz configuration change: channel-switch MCU timeout, PCIe completion timeouts, repeated failed full resets; a warm reboot did not recover Wi-Fi | Adapt the idea, not the patch unchanged: verify NPU DMA-stop acknowledgement before reclaiming/rebuilding rings; propagate stop failure; quiesce scan/NAPI/work queues consistently; only resume traffic after successful NPU/ring handoff. The supplied patch ignores the return from `mt7996_npu_hw_stop()`. It does not explain the initiating channel-switch/PCIe failure by itself. |

## Useful with separate compatibility validation

- **039 + 046 statistics:** integrate polling with ACK72's existing AIR_TIME/RSSI
  work instead of inserting duplicate periodic MCU queries. Verify that firmware
  counters are cumulative or interval counters, and that switching from software
  counters on zero values does not make totals jump/backtrack after reset. This
  can improve offloaded station statistics; it cannot measure network latency.
- **032 small BlockAck windows:** a focused Apple-client compatibility experiment
  if a failing station actually negotiates a window below 64. Gilly's hardware
  limitation statement is an author claim, not independently proven by our tests.
  Preserve offload for ordinary bulk queues and record negotiated BA parameters.
- **033 session teardown:** resolve synchronization between asynchronous status
  events and teardown, valid session ID zero, stale events, and MLO link selection
  before use. A mutex held only by the reader is not sufficient synchronization.
- **027 NPU station bitmap clear:** confirm the stock firmware message ABI, valid
  WCID/TID range and completion/failure semantics before index reuse. Its prose
  says TIDs 0–7 but the loop sends 0–8, and failures are silently skipped.
- **957 BQL and TX pointer cleanup:** now checked against Linux stable 6.18.52
  with all 68 selected patches affecting the four Airoha Ethernet/NPU files
  replayed successfully. TX teardown still frees pending SKBs without BQL
  completion, and ordinary completion leaves `e->skb` stale. Port the BQL
  accounting and pointer clearing, with stop-under-load validation across shared
  netdev queues. The current cleanup skips entries with `dma_addr == 0`, so the
  stale pointer alone does not prove the particular UAF claimed in the patch
  description. No such UAF was observed in the current test.
- **980 RX_NO_CPU_DSCP IRQ:** the prepared handler still acknowledges these
  enabled interrupt bits but only routes RX_DONE to NAPI. The patch passes
  application checks against the current files. Recommend a separate fix and
  ring-pressure test covering both interrupt banks, masking/rearming and queue
  31. This is a concrete missed-wakeup candidate for Ethernet RX stalls, not
  proof of the cause of Wi-Fi PCIe Completion Timeout. Patch application and
  source review are not cross-compilation or runtime validation.
- **963 MIB collection:** removing periodic reset can avoid counter loss, but
  review 64-bit high/low read consistency, reset detection, wrap and multiple
  devices per GDM. Prefer consuming kernel-exported software totals in dashboards
  over changing hardware accounting merely to make raw-MMIO graphs look stable.

## Already present or unsuitable as a blanket import

Effective mt76 already has the 019 boundary `break`, the 037 twelve-byte delete
event layout, 041 `INVALID_REG_ADDR`, and 043 teardown/ALTX handling. The six
selected fixes 034/035/036/042/045/048 are already included. The kernel already
contains the queue-31 RX_DONE fix corresponding to 976 and uses `NETIF_F_GRO_HW`;
do not import the entire 975/977 series over it.

981 remains unsuitable as written: its timeout path can reclaim RX buffers
without confirmed DMA stop, and its work-disable/re-enable lifecycle needs
review. Whole DTS, kernel config, mt76 Makefile, regulatory DB, interface
defaults and prebuilt NPU files should not be copied. They change the board
identity, source/dependency model, clocks, recovery logging, regulatory behavior
or user network configuration alongside the intended fix.

FlowSense's missing latency was independently traced to its disabled sampler.
This builder now uses a low-rate, bounded RTT sampler and displays the mean,
jitter, successful replies/attempts, target and stale state. Loss remains in
the sampler data. No packet-path kernel patch is required for that fix.

The [channel/recovery follow-up](wifi-recovery-review-20260921.md) identifies
additional scan-completion and failed-restart handling gaps not covered by
047. These must be addressed alongside its NPU lifecycle changes; importing
047 alone is not a complete PCIe recovery fix.

Source: https://github.com/Gilly1970/Gemtek-W1700K-6.18/tree/0aa0666de1366b69d5d73d98c19809affc1f76ed/openwrt-patches
