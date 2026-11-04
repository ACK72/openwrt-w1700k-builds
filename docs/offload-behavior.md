# Offload counters and shared resources

The mt7996 watchdog collects station statistics once per device interval,
including on Airoha NPU systems. Multiple active radios share the poll and its
error backoff. Rate, airtime and RSSI queries remain enabled.

For a non-MLO station using NPU offload, packet counts come from the firmware
MSDU totals accumulated by the driver. They can remain zero until the first
report and update at the polling interval. A zero or failed poll does not
switch reporting back to mac80211. The existing 32-bit packet counter wrap
still applies. Byte counts use mac80211 consistently because firmware byte
reports are not populated on every NPU band; these byte counts can therefore
undercount offloaded traffic. MLO keeps its existing reporting until accounting
across active and removed links is supported. WED reporting is unchanged.

IPv6 hardware flows leaving a GDM port use a separate source-MAC slot for each
distinct egress MAC, including addresses used by VLAN uppers. Flows with the
same MAC share a reference-counted slot. Each registered GDM port reserves its
own base slot (IDs 1–4); the hardware's preserve-MAC slot 15 is also reserved.
Slot 0 and base indices without a registered GDM port join the pool. Changing
an interface's base address cannot rewrite the MAC used by an existing flow.

After the last flow releases a slot, its cached MAC can be reused without a
hardware write or replaced by a different MAC. The allocator uses never-used
slots first, then the least recently released slot. Live flows are never
evicted. The pool holds 15 minus the number of registered GDM ports distinct
MACs simultaneously (at least 11 with four ports), with no lifetime limit on
MAC turnover. This counts IPv6 egress source MACs, not connected Wi-Fi clients
or the number of flows sharing an address.

Flow deletion checks hardware invalidation before releasing its MAC. Moving a
flow to another hardware entry first removes the previous binding; a failed
removal retains its owner. A timed-out MAC write or uncertain flow programming
quarantines only the affected slot until full hardware initialization; a flow
with an earlier hardware error cannot make its slot reusable on final deletion.
Each quarantined slot is logged once ("IPv6 source MAC slot N quarantined until
the PPE is reinitialized"); reloading the Ethernet driver or rebooting returns
it to the pool. When all usable slots have live references or are quarantined,
additional distinct MACs use software forwarding. Slot reuse relies on the existing PPE
invalidation/ACK and coherent-memory ordering contract; software fault tests
do not establish hardware pipeline timing. IPv4 inline MAC handling and bridge
subflows that preserve the original source MAC retain their existing behavior.

Hardware LRO comes from the upstream backport (airoha 194) and is a QDMA-wide
engine. It is off by default and can be enabled per interface with ethtool. A
second interface on the same QDMA cannot open while it is enabled, and closing
the interface or disabling LRO on it turns the engine off. Aggregates with
too many segments or no TCP payload are dropped and counted as RX drops; a
segment count of zero or one is delivered as an ordinary packet.

These adaptations derive from Gilly's 039/046 and 972/973 ideas, with source
links and contributor attribution in their build patches.
See the [pinned source patch collection](https://github.com/Gilly1970/Gemtek-W1700K-6.18/tree/4b8fb8c3a2619dd239fb44fd511ee2848a07e768/openwrt-patches).

## Guarded forwarding and control paths

Single-descriptor NPU RX packets use a separate path with the same completion,
buffer and length checks as fragmented packets. Multi-descriptor packets still
wait for the whole chain before any page ownership changes. Receive delivery
and station power-save processing retain their per-packet ordering.

Ordinary queued pending TX payloads publish up to four descriptors per kick.
Control, status-requested, port-control, offchannel and power-save/DTIM traffic
is published immediately. Ring changes, enqueue errors, queue stops, exhausted
budgets and function exit flush pending publication. PHY and ring admission
budgets and WCID FIFO order are unchanged. Fewer kicks do not imply the same
percentage improvement in throughput; device latency and RF tests are needed.

Cross-ingress L2 collisions still use the existing software fallback window.
Ingress metadata is resolved only when an L2 fallback entry is found. These
changes do not make an ambiguous hardware flow key safe to share.

WLAN SET mailbox commands omit unused reply payload copies but still check
completion status. Sleepable initialization retries retain their 10 ms minimum
settling interval while yielding the CPU. This reduces busy waiting, not the
required settling time. The atomic PPE mailbox protocol is unchanged.

TRTCM configuration follows the upstream backport (airoha 187): each write
waits for completion and succeeds only after a matching readback of the low
word. A timed-out write, failed read or mismatch is retried once more; after
that the configuration fails with -EBUSY.

Power-table construction reuses temporary memory after the acknowledged rate
upload. Both table uploads, regulatory/SAR/board limits and recalculation remain
in place. There is no firmware power-table cache or raised power limit. Failed
recovery still blocks MMIO and traffic restart until the existing recovery
requirements are met.

## Known limitation: WAN flow control at 1 Gbps

On a line that an ISP limits with PAUSE on a 1 Gbps link, a single TCP upload stays
far below the line rate, about 27 Mbps on a 100 Mbps line. With TX fragmentation off
(`TX_FRAG_LEN` 31) the XSI MAC sends two or three more frames after it receives XOFF,
and the ISP drops what exceeds its headroom. This firmware does not fix it.

Lowering `TX_FRAG_LEN` was tried and removed. In short runs with frames of about
1,350 bytes, values 2 to 16 reached about 100 Mbps with almost no retransmissions.
Larger frames under sustained upload then failed every time, in the same order: the
TX FIFO underrun bit in `INT_STS`, the link going down, the link returning about 3 s
later, and no TX afterwards, while RX continued. DHCP cannot complete, so the WAN
loses its address. Each value was measured once:

| `TX_FRAG_LEN` | TX FIFO AEMPTY | XOFF before underrun | Data before underrun |
| ---: | ---: | ---: | ---: |
| 4 | 22 | 28,455 | 217 MB |
| 8 | 22 | 3,572 | 27 MB |
| 12 | 22 | 60 | 0.6 MB |
| 4 | 96 | 1,605 | 12 MB |

Writing 30 stalled TX within a second, so do not write this field on a running MAC.
Taking the device down and up recovers a stalled MAC without a reboot:

```sh
ip link set dev wan down; sleep 3; ip link set dev wan up
```

The same command recovered a WAN that stayed without a link after its cable was
plugged in, while the PHY reported 1 Gbps. That failure is intermittent and its cause
is unknown.

These had no effect on the frames sent after XOFF, on retransmissions, or on both:
the TX data FIFO almost-full threshold, the TX header FIFO threshold, `PSE_FC_CFG` bit
23, the pause quanta cycle and a QDMA channel limit at the link rate. The WAN MAC has no
FE fragment register, and the RTL8261CE driver offers no rate adaptation or other host
modes. The meaning of `TX_FRAG_LEN`, and why the vendor keeps 31 on this MAC, are not
documented.

A built-in switch port avoids this MAC. With `lan3` as the WAN on the same line, uploads
reached 87 to 94 Mbps over 2.9 GB without a link loss, in a test of about 4 minutes.
It only suits lines up to 1 Gbps. Take the port out of `br-lan` before connecting the
ISP cable: on the bridge it joins the ISP to the LAN, and `dnsmasq` then turns off LAN
DHCP until a reboot.
