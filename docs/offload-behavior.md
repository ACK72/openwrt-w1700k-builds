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
When all usable slots have live references or are quarantined, additional
distinct MACs use software forwarding. Slot reuse relies on the existing PPE
invalidation/ACK and coherent-memory ordering contract; software fault tests
do not establish hardware pipeline timing. IPv4 inline MAC handling and bridge
subflows that preserve the original source MAC retain their existing behavior.

Hardware GRO belongs to the shared QDMA. Feature changes remain synchronized
across its interfaces, and the engine is disabled when its last interface
closes. A change while all interfaces are down updates their feature state
without programming the engine. Zero or oversized aggregate counts and empty
TCP payloads are rejected before an aggregate SKB is allocated.

These adaptations derive from Gilly's 039/046, 972/973 and selected 975/977
ideas, with source links and contributor attribution in their build patches.
See the [pinned source patch collection](https://github.com/Gilly1970/Gemtek-W1700K-6.18/tree/4b8fb8c3a2619dd239fb44fd511ee2848a07e768/openwrt-patches).
