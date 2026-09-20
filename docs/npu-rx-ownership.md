# NPU RX ownership correction

The official-NPU W1700K image produced page-pool warnings and later a fatal
DMA cache synchronization fault in `mt76_npu_rx_poll`. The first invalid
address producer is not proven by a stack trace alone. Source review found
an independently reproducible ownership defect: if a later descriptor is
incomplete, `mt76_npu_dequeue()` frees an skb containing earlier pages while
leaving those same pages owned by the RX ring. A subsequent poll can reuse
or return them again.

Patch 0007 waits for the complete chain before transferring any page. It
reads metadata after DMA completion, checks posted entries and lengths,
consumes complete invalid/allocation-failed packets exactly once, and clears
consumed software entries. Refill publishes the address after clearing the
old completion. Zero-copy, page-pool recycling, ring sizes and NPU offload
are retained; no sleep or bandwidth cap is added.

An invalid software buffer/count is reported and left unconsumed, rather
than DMA-synchronizing an invalid address or guessing which page to free.
Such a diagnostic still fails runtime acceptance and requires investigation.
This protection does not make arbitrary pre-existing memory corruption safe.

`tests/test_npu_rx.py` extracts the original and replacement dequeue bodies
from the shipped patch and executes them with mocked kernel APIs. The
original fails the partial-chain ownership scenario. Fourteen scenarios
cover partial publication and retry, wrap-around, allocation failure, empty
queues with stale DONE, count/length bounds, missing buffers/DMA addresses,
and metadata made visible at the mocked DMA barrier. These tests cannot
prove real ARM ordering, firmware behavior or long-term device stability.
The full firmware build and device tests remain required.

The GitHub upgrade buttons also serialized `disabled=false` as an HTML
attribute. Root had write permission but the attribute still disabled all
three actions. Writable sessions now omit the attribute using LuCI's null
convention. Read-only/denied sessions retain disabled controls and the
existing backend ACLs are unchanged. The view regression tests exercise all
three buttons for writable, read-only and denied sessions.
# GitHub upgrade follow-up

Live testing also found two backend issues after enabling the buttons:

* OpenWrt builds jq without Oniguruma. The release filter now uses ASCII character
  and exact prefix/suffix checks instead of `test()`, preserving the tag, image,
  URL and SHA-256 restrictions. Invalid and duplicate assets remain excluded.
* Returning from BusyBox ash with a background worker and a final builtin
  `printf` consistently timed out through `rpcd file.exec`, even after the worker
  had completed. Ending the foreground helper with `exec /bin/echo` returned in
  about 0.2 seconds in five consecutive device tests. The worker retains its
  separate stdin/stdout/stderr; operation completion is still polled separately.

`tests/test_upgrade_releases.py` tests the actual helper filter. Its three test
methods (including malformed metadata cases) also passed using the installed
router jq, without adding a regex library or expanding web ACLs.
