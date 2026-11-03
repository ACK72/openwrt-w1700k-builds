# Official kmod compatibility

The firmware keeps the official snapshot's vermagic and package feeds, so
`apk add kmod-...` installs modules that the official buildbot compiled. The
local kernel is not the official one: fanboy and W1700K patches change its
sources, and fanboy changes its configuration. OpenWrt's own protection, a
vermagic derived from the kernel configuration, is replaced on purpose, and
the kernel has no symbol versioning. A module built for a different structure
layout or function signature therefore usually loads and then misbehaves.

Official kmods are safe only while every difference keeps the interfaces they
use. The modules built into the image come from the same tree and are not
affected.

## Reviewed differences

[`patches/abi-review.json`](../patches/abi-review.json) lists every reviewed
difference with its verdict and reason. In short:

| Difference | Verdict |
| --- | --- |
| Patch 0011 names QDMA NAPI threads | Compatible: names live in a net/core table, `struct napi_struct` keeps the official layout |
| 603, 672, 675-01, 675-03, 675-05, 886 (fanboy) | Compatible: no layout or exported interface used by official modules changes |
| Kernel configuration (fanboy) | Safe failure only: official pstore kmods do not load |
| Profile kernel options | Compatible |

Official kmods that cannot work on this firmware:

- **pstore/ramoops**: built into this kernel.
- **mt76 drivers other than mt7996** (for example `kmod-mt7921e` or
  `kmod-mt7915e`): the image's `kmod-mt76-core` and `kmod-mt76-connac` carry
  the fanboy and W1700K patches, so official drivers built without them would
  load against different structures. The review below does not cover
  out-of-tree packages, so do not install these.

The source composition sets the release of the image's mt76 and hostapd
packages to the official release plus 100 (`release_offset` in
[`patches/w1700k/series.json`](../patches/w1700k/series.json)), which keeps
them above official builds of the same source, including later release-only
bumps. Once the official feeds update the mt76 or hostapd source, their
packages have a higher version, and `apk upgrade` would replace the image's
ones and drop these patches, including the NAPI names the affinity policy
requires. Do not upgrade `kmod-mt76*`, `kmod-mt7996*`, `hostapd*` or `wpad*`
from the official feeds; install a newer image instead.

## When the review stops a build

`scripts/abi_review.py` runs after the source composition. It compares the
composed tree with the official OpenWrt revision it is based on and stops when
a kernel patch changes `include/` differently from the official tree, when the
kernel configuration files differ, or when the profile's `CONFIG_KERNEL_*`
options change, unless the change has a reviewed entry. Fingerprints cover only
changed lines, so a rebase that moves context does not need a new review.

For each reported change:

1. Find the modules that use the changed structure, enum, macro or function,
   for example with a code search of the kernel tree.
2. Decide whether a module from the official feeds can use it. Built-in code
   and modules shipped in the image are not affected.
3. If an official module can, change the patch so that the official interface
   stays.
4. Add the printed entry to `patches/abi-review.json` with the verdict and the
   reason, and remove entries that the script reports as no longer present.

Entries in `official_must_not_contain` stop the review when the official tree
gains the given line, for example to drop a compatibility patch once the
official kernel carries the change it works around.
