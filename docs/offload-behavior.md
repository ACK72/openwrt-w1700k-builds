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
same MAC share a slot. GDM base slots 0–4 and the hardware's preserve-MAC slot
15 are reserved; changing an interface's base address cannot rewrite the MAC
used by an existing flow.

Slots 5–14 remain assigned until full hardware initialization. They are not
recycled when a flow is deleted, since deletion does not prove that all
in-flight packets have stopped referencing the slot. This supports ten
distinct IPv6 egress MACs per hardware lifetime. Further distinct addresses
continue through software forwarding. A timed-out hardware write also reserves
its slot without making it available to flows. Interface restart or firewall
reload does not reclaim these slots. IPv4 inline MAC handling and bridge
subflows that preserve the original source MAC retain their existing behavior.

Hardware GRO belongs to the shared QDMA. Feature changes remain synchronized
across its interfaces, and the engine is disabled when its last interface
closes. A change while all interfaces are down updates their feature state
without programming the engine. Zero or oversized aggregate counts and empty
TCP payloads are rejected before an aggregate SKB is allocated.

These adaptations derive from Gilly's 039/046, 972/973 and selected 975/977
ideas, with source links and contributor attribution in their build patches.
See the [pinned source patch collection](https://github.com/Gilly1970/Gemtek-W1700K-6.18/tree/4b8fb8c3a2619dd239fb44fd511ee2848a07e768/openwrt-patches).
