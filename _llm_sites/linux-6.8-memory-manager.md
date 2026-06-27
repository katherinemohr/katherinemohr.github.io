# The Linux Memory Manager, Bottom to Top (Linux v6.8)

*A low-level guide for readers with undergraduate operating-systems background.*

This guide describes how physical and virtual memory are organized and managed in the
Linux kernel as of **version 6.8** (released March 2024). It is grounded conceptually in
Mel Gorman's *Understanding the Linux Virtual Memory Manager* (which describes the 2.4/2.6
kernels) but every mechanism, structure name, and policy below reflects the **current
6.8 source tree**, which has diverged substantially from the book. Where the book and the
modern kernel describe the same idea — zones, the buddy allocator, the page cache, page
replacement — the names and shapes of the data structures have changed, and several whole
subsystems (folios, the maple tree, the multi-generational LRU, 5-level paging, `memblock`)
did not exist when the book was written. This document describes 6.8 as it actually is.

The examples and file paths assume the **x86-64** architecture unless stated otherwise,
because that is where the most concrete detail lives, but the core abstractions
(`pglist_data`, zones, the buddy allocator, `address_space`, the page-table accessors) are
architecture-independent.

---

## Table of contents

1. [Orientation: the layers of the memory manager](#1-orientation)
2. [Physical memory model: pages, folios, and `mem_map`](#2-physical-memory-model)
3. [Zones and NUMA nodes](#3-zones-and-numa-nodes)
4. [How memory is detected and bootstrapped at boot time](#4-boot-time-memory-detection)
5. [Page allocation: the buddy allocator and its surroundings](#5-page-allocation)
6. [The page cache (the modern "file buffer cache")](#6-the-page-cache)
7. [Page reclaim, the OPT ideal, and the LRU approximations](#7-page-reclaim-and-opt)
8. [Page migration and compaction](#8-page-migration-and-compaction)
9. [Page tables: the x86-64 multi-level walk](#9-page-tables)
10. [Virtual address spaces: VMAs and the page fault handler](#10-address-spaces-and-faults)
11. [How the pieces fit: the life of an allocation](#11-putting-it-together)
12. [Glossary](#12-glossary)
13. [Source map and further reading](#13-source-map)

---

<a name="1-orientation"></a>
## 1. Orientation: the layers of the memory manager

It helps to fix the vocabulary before diving in, because "memory management" in Linux is
really several cooperating subsystems stacked on top of each other. From the hardware up:

**Physical page frames.** The smallest unit the kernel allocates is a hardware page, almost
always 4 KiB on x86-64 (`PAGE_SIZE`, `PAGE_SHIFT == 12`). Every physical page frame is
described by a `struct page` (and, increasingly, grouped into a `struct folio`). The kernel
keeps an array of these descriptors so it can map a *physical frame number* (PFN) to its
metadata in O(1).

**The physical allocator (buddy system).** Physical frames are handed out by the **buddy
allocator**, which manages free memory in power-of-two blocks ("orders") per zone. This is
the lowest-level allocator; everything else is built on it. The slab/SLUB allocator,
`vmalloc`, the page cache, and user page faults all ultimately call into the buddy allocator
to get raw frames.

**Zones and nodes.** Physical memory is partitioned first by **NUMA node** (a `pglist_data`,
representing the memory attached to one set of CPUs/sockets) and within each node by **zone**
(`struct zone`: `ZONE_DMA`, `ZONE_DMA32`, `ZONE_NORMAL`, `ZONE_MOVABLE`, `ZONE_DEVICE`).
Zones exist because not all physical memory is interchangeable — old DMA devices can only
address low memory, some memory must remain migratable, and so on.

**The slab allocators (SLUB).** For objects smaller than a page (inodes, `task_struct`s,
network buffers), the kernel uses the **slab** layer — in 6.8 the only surviving
implementation is **SLUB** (`mm/slub.c`; SLOB and the original SLAB allocator have both been
removed). SLUB carves buddy-allocated pages into fixed-size object caches. This guide
touches slab only in passing; it is a consumer of the buddy allocator.

**Virtual memory and page tables.** Each process has an address space described by an
`mm_struct`, a set of memory regions (`vm_area_struct`s, now indexed by a **maple tree**
rather than the old red-black tree), and a hierarchical **page table** rooted at a PGD. The
hardware MMU walks these tables to translate virtual addresses to physical frames; the kernel
fills them in lazily on page faults.

**The page cache and reclaim.** File data and anonymous memory live in physical frames that
are tracked for reclaim. The **page cache** (`address_space` + an XArray of folios) caches
file contents; **reclaim** (`kswapd`, direct reclaim, the LRU lists / MGLRU) decides which
frames to evict when memory runs low. **Migration** and **compaction** move physical pages
around to defragment memory, balance NUMA locality, or free up removable memory.

A mental model that stays accurate throughout: **the buddy allocator owns free physical
frames; zones and nodes describe where those frames physically are and what they're good for;
page tables describe where frames are virtually visible; and the page cache plus reclaim
decide what gets to stay resident.**

---

<a name="2-physical-memory-model"></a>
## 2. Physical memory model: pages, folios, and `mem_map`

### 2.1 `struct page`

Every physical frame the kernel manages has a `struct page` (defined in
`include/linux/mm_types.h`). This descriptor is deliberately tiny — on the order of 64 bytes
— because there is one for *every* frame in the system, and on a large machine that array can
consume a meaningful fraction of RAM. To stay small, `struct page` is heavily **unionized**:
the same bytes mean different things depending on what the frame is currently being used for
(a buddy free block, a page-cache page, a slab page, an anonymous page, a page-table page,
etc.). Fields like `flags`, `_refcount`, and `_mapcount` are the durable ones; much of the
rest is overlaid context.

The `flags` field is a packed bitfield (`enum pageflags` in
`include/linux/page-flags.h`) holding both true flags (`PG_locked`, `PG_dirty`,
`PG_uptodate`, `PG_lru`, `PG_reserved`, `PG_writeback`, ...) and, in its high bits, the
encoded **node id, zone number, and (under sparsemem) section** of the frame — this is how
`page_to_nid()` and `page_zonenum()` work without a separate lookup.

### 2.2 Folios — the major change since the book

The single biggest structural change to the memory manager in the years before 6.8 is the
introduction of the **folio** (`struct folio`, `include/linux/mm_types.h`). A folio is a
container for one or more *physically contiguous* pages that are managed as a unit, and it is
guaranteed never to be a "tail" page of a compound page. The motivation is twofold: it makes
the *head page vs. tail page* distinction explicit in the type system (eliminating a class of
bugs where code accidentally operated on a tail page), and it lets the kernel manage memory
in larger chunks than 4 KiB without pretending each base page is independent.

By 6.8 the page cache, the LRU/reclaim machinery, anonymous memory, and large chunks of the
filesystem interface have all been converted to operate on **folios** rather than bare
`struct page`s. When you read modern code you will see `folio_get`, `folio_lock`,
`folio_mapping`, `folio_nr_pages`, `folio_test_dirty`, and so on, where the 2.6-era code (and
Gorman's book) used `page_cache_get`, `lock_page`, `page_mapping`, etc. A folio of order 0 is
just one page; higher-order folios back **large folios** in the page cache and transparent
huge pages. Conceptually, **think of the folio as the new unit of memory management, and the
page as the unit of hardware addressing.**

### 2.3 Mapping a PFN to its descriptor: the memory model

To turn a physical frame number into its `struct page`, the kernel needs the descriptor
array. How that array is laid out is the **memory model**, selected at build time:

- **FLATMEM** — a single contiguous `mem_map[]` array. Simple, used on small/embedded systems
  with one contiguous bank of RAM.
- **SPARSEMEM** and **SPARSEMEM_VMEMMAP** — the default on x86-64 and essentially all large
  systems. Physical memory is divided into fixed-size **sections** (`struct mem_section`),
  each covering a range of PFNs, so that physical address spaces with large holes (memory-
  mapped devices, reserved regions, hot-pluggable banks) don't waste a descriptor for every
  absent frame. **SPARSEMEM_VMEMMAP** goes further and maps a *virtual* array of `struct page`
  descriptors (`vmemmap`) so that `pfn_to_page()` and `page_to_pfn()` reduce to simple pointer
  arithmetic on a virtual address, while the underlying physical backing for the descriptors
  is allocated only for present sections. This combines FLATMEM's O(1) access with
  SPARSEMEM's tolerance of holes, which is why it is the default.

This is a real divergence from the book era, where `DISCONTIGMEM` and a simpler `mem_map`
were the norm; `DISCONTIGMEM` has been removed entirely. The accessors you use —
`pfn_to_page()`, `page_to_pfn()`, `virt_to_page()` — are stable across all models; only the
implementation underneath changes.

---

<a name="3-zones-and-numa-nodes"></a>
## 3. Zones and NUMA nodes

### 3.1 Why nodes exist: NUMA

On a **Non-Uniform Memory Access** (NUMA) machine, physical memory is partitioned among
sockets/controllers. A CPU can reach memory attached to its own socket (its **local node**)
faster and with more bandwidth than memory on another socket (a **remote node**, reached
across an interconnect such as UPI or Infinity Fabric). The "non-uniform" is exactly this:
the cost of a memory access depends on which node holds the memory relative to which CPU
issues the access.

Linux models each such memory domain as a **node**, represented by a `struct pglist_data`
(typedef'd `pg_data_t`, defined in `include/linux/mmzone.h`). A uniprocessor or
single-socket machine has exactly one node (node 0); a UMA system is just the degenerate
one-node case of the same code. The key fields of `pglist_data` are:

- `node_zones[MAX_NR_ZONES]` — the array of zones belonging to this node.
- `node_zonelists[MAX_ZONELISTS]` — the **fallback order** in which zones (across *all* nodes)
  should be tried when satisfying an allocation that started here (described below).
- `node_start_pfn`, `node_present_pages`, `node_spanned_pages` — where this node's physical
  memory begins and how much of its PFN span is actually populated (`present` ≤ `spanned`
  because of holes).
- `node_id`, plus per-node reclaim state: the node's `kswapd` kernel thread, `kcompactd`
  thread, the `lruvec` (LRU lists / MGLRU state), and per-node watermarks/statistics.

In 6.8 the **LRU lists and most reclaim accounting live at the node level**, inside the
`pglist_data` and its `lruvec`, rather than per-zone (in 2.6 the LRU lists were per-zone; they
were moved to per-node "node-based reclaim" because reclaim decisions are more sensibly made
over a whole node's working set than zone-by-zone). One refinement to keep in mind: with the
memory controller (`memcg`, cgroup v2) enabled, there is actually **one `lruvec` per memory
cgroup per node**, not a single global one — reclaim and the LRU lists are *cgroup-aware*, so
a container hitting its memory limit reclaims its own pages. The node-level `lruvec` is the
root cgroup's; conceptually you can read "per-node lruvec" as "per-(cgroup, node) lruvec" for
the rest of this guide. See Section 7.7 for more on memcg.

### 3.2 Why zones exist: addressing and migratability constraints

Within a node, not all physical frames are interchangeable, so each node's memory is further
divided into **zones** (`enum zone_type`, `struct zone`). A zone is a contiguous-by-purpose
range of frames with a shared constraint. In 6.8 the zone types, in address order, are:

- **`ZONE_DMA`** — the lowest physical memory, for ancient devices that can only address a
  very small range (on x86, historically the first 16 MiB for ISA DMA). Present only if
  `CONFIG_ZONE_DMA` is set. It is small and precious; the kernel avoids allocating from it
  unless a caller specifically needs it.
- **`ZONE_DMA32`** — memory addressable with a 32-bit DMA mask, i.e. below 4 GiB. Many modern
  devices have 32-bit DMA limitations, so this zone exists on 64-bit systems to satisfy
  `GFP_DMA32` allocations. Present if `CONFIG_ZONE_DMA32`.
- **`ZONE_NORMAL`** — the workhorse. On 64-bit systems this is the bulk of RAM, directly
  mapped into the kernel's address space and usable for essentially any purpose. Most
  allocations land here.
- **`ZONE_MOVABLE`** — a pseudo-zone containing only frames the kernel promises are
  *migratable* (movable user pages, page cache), never pinned kernel data. Its purpose is to
  keep a region defragmentable and removable, which is what makes **memory hot-unplug** and
  reliable huge-page allocation possible. It is sized administratively (e.g. the
  `kernelcore=`/`movablecore=` boot parameters, or hotplug policy) rather than by hardware.
- **`ZONE_DEVICE`** — not normal system RAM at all. It describes persistent memory (PMEM),
  device-private memory (e.g. GPU memory), and other physical address ranges that have
  `struct page` descriptors so they can participate in the memory APIs (`get_user_pages`,
  DMA, migration) without being part of the buddy allocator's free pools. Present if
  `CONFIG_ZONE_DEVICE`.

The classic 32-bit `ZONE_HIGHMEM` is effectively **dead on 64-bit**: the entire physical
range fits in the kernel's direct map, so the kernel never needs the temporary `kmap()`
mappings that 32-bit systems used to reach memory above the directly-mapped region. The
`kmap_local_*` APIs still exist for the architectures and code paths that need them, but the
highmem problem does not arise on x86-64.

### 3.3 Inside a `struct zone`

A `struct zone` is the unit the buddy allocator actually operates on. Its important fields:

- `free_area[NR_PAGE_ORDERS]` — the **buddy free lists**, one bucket per allocation order
  (Section 5). `NR_PAGE_ORDERS` is `MAX_PAGE_ORDER + 1`; on x86-64 the default
  `MAX_PAGE_ORDER` is 10, so the largest buddy block is 2¹⁰ = 1024 contiguous pages (4 MiB).
  (`MAX_PAGE_ORDER` is *inclusive* — the highest valid order — so the number of buckets is
  `NR_PAGE_ORDERS == MAX_PAGE_ORDER + 1`.)
- `_watermark[NR_WMARK]` — the **min / low / high** watermarks (plus `WMARK_PROMO` used by
  NUMA balancing) that drive reclaim and allocation back-pressure (Section 5.4).
- `per_cpu_pageset` / `struct per_cpu_pages` — the **per-CPU page (PCP) lists**, small caches
  of free order-0 (and small-order) pages held per-CPU so the common single-page
  allocation/free path can avoid taking the zone's main lock.
- `lock` — the zone spinlock guarding the free areas.
- `zone_start_pfn`, `spanned_pages`, `present_pages`, `managed_pages` — bookkeeping for the
  zone's physical extent and how many pages the buddy allocator actually owns (`managed` is
  what's left after boot reservations).
- `vm_stat[]` — per-zone statistics (free pages, etc.) exposed via `/proc/zoneinfo`.

### 3.4 Zonelists: how a zone is chosen for an allocation

When code requests memory, it names a **preferred zone** indirectly through GFP flags (e.g.
`GFP_KERNEL` permits `ZONE_NORMAL` and below; `GFP_DMA32` caps at `ZONE_DMA32`) and an
implicit *preferred node* (usually the running CPU's local node). But the allocator must be
able to **fall back** when the preferred zone is empty. That fallback order is precomputed
into each node's **zonelists** (`node_zonelists`).

There are two zonelists per node:

- `ZONELIST_FALLBACK` — the ordered list of zones to try, spanning *all* nodes, when the
  allocation is allowed to use remote memory rather than fail.
- `ZONELIST_NOFALLBACK` — only this node's zones, for allocations that must stay local
  (`__GFP_THISNODE`).

The ordering within the fallback list balances two competing goals: prefer **local memory**
(NUMA locality) and prefer **higher zones** (don't burn scarce `ZONE_DMA`/`DMA32` on requests
that `ZONE_NORMAL` could satisfy). The default policy (**node ordering**) exhausts all of the
local node's zones before stepping to the nearest remote node, using ACPI **SLIT** distance
information to order remote nodes nearest-first. Each entry in a zonelist is a `struct
zoneref` carrying a zone pointer and its zone index, so the allocator can cheaply skip zones
that are too high for the request's GFP mask. The slow path walks this list in order, checking
watermarks at each zone (Section 5).

### 3.5 NUMA allocation policy

On top of the mechanical zonelist fallback sits **NUMA memory policy** (`mm/mempolicy.c`),
which lets userspace and the kernel express *where* memory should come from:

- **`MPOL_DEFAULT`** — local-node allocation (allocate on the node of the faulting CPU).
- **`MPOL_BIND`** — restrict allocations to a specific node set.
- **`MPOL_PREFERRED`** — prefer a node but fall back if it's full.
- **`MPOL_INTERLEAVE`** — round-robin allocations across a node set, to spread bandwidth.
- **`MPOL_PREFERRED_MANY`** (newer) — prefer a *set* of nodes.

Policies are set with `set_mempolicy()`, `mbind()`, and `numa_set_membind()`, and are visible
through `numactl`. Separately, **automatic NUMA balancing** (Section 8.4) periodically samples
where a task's pages live versus where the task runs and migrates pages toward the using CPU,
so that even programs that know nothing about NUMA gradually get better locality.

---

<a name="4-boot-time-memory-detection"></a>
## 4. How memory is detected and bootstrapped at boot time

There is a bootstrapping paradox at the heart of early memory management: the buddy allocator
and `struct page` array are themselves data structures that must be allocated *in memory* —
but the normal allocator that would allocate them does not exist yet. Linux resolves this with
a sequence: **(1) discover the physical memory map from firmware, (2) record it in a simple
boot-time allocator called `memblock`, (3) use `memblock` to allocate the page descriptor
array and the kernel's own early structures, and finally (4) hand all remaining free memory
over to the buddy allocator and retire `memblock`.**

### 4.1 Discovering the physical map (firmware)

The kernel cannot probe RAM by poking addresses; it must ask the firmware what physical
address ranges exist and what they are for.

- On **legacy BIOS x86**, the bootloader/early kernel obtains the **e820 map** (named after
  the `INT 0x15, EAX=0xE820` BIOS call). Each e820 entry is a `(base, length, type)` triple,
  where the type marks the range as usable RAM, reserved, ACPI reclaimable, ACPI NVS, bad
  memory, etc. The kernel's copy and processing live in `arch/x86/kernel/e820.c`
  (`e820__memory_setup`, the `e820_table`). Only ranges marked usable become candidate RAM;
  reserved/ACPI/MMIO ranges are explicitly excluded so the kernel never hands them to the
  allocator.
- On **UEFI** systems the equivalent information is the **EFI memory map**, a table of
  `EFI_MEMORY_DESCRIPTOR` entries with their own type taxonomy (conventional memory, runtime
  services code/data, ACPI, MMIO, ...). The kernel consumes it via the EFI stub and converts
  it into the same internal representation.

The result of this step is a normalized list of "this physical range is RAM the kernel may
use" versus "hands off."

### 4.2 `memblock`: the boot-time allocator

Discovered ranges are recorded in **`memblock`** (`mm/memblock.c`), the early physical memory
manager that *replaced* the old `bootmem` allocator described in Gorman's book. `memblock`
keeps two arrays of `(base, size)` regions:

- **`memblock.memory`** — all physical RAM the kernel knows about.
- **`memblock.reserved`** — sub-ranges already spoken for (the kernel image itself, the
  initrd, firmware tables, early page tables, the `memblock` arrays, etc.).

Early code calls `memblock_add()` to register RAM and `memblock_reserve()` to carve out
in-use regions; `memblock_alloc()` (and `memblock_phys_alloc*`) satisfy early allocations by
finding a free gap (memory minus reserved) and marking it reserved. It is deliberately simple
— a linear list with first-fit/last-fit semantics and no `struct page` dependency — because it
must work before the page allocator and even before the final page tables exist. `memblock`
also records NUMA node ownership per region (`memblock_set_node`), so early allocations can be
node-aware.

### 4.3 Topology: NUMA nodes and zone boundaries

To partition memory into nodes and zones, the kernel parses firmware topology tables:

- **ACPI SRAT** (System Resource Affinity Table) — maps physical address ranges and CPUs to
  **proximity domains** (which become Linux nodes). This is how the kernel learns "frames
  A..B belong to node 1, and CPUs X,Y are local to node 1."
- **ACPI SLIT** (System Locality Information Table) — a matrix of relative **distances**
  between nodes, used to order zonelists nearest-first and to inform reclaim/balancing.

Zone boundaries within the discovered RAM are then computed from architecture limits:
`ZONE_DMA`/`ZONE_DMA32` are capped at their hardware-defined physical addresses (e.g. 16 MiB,
4 GiB on x86), `ZONE_NORMAL` takes the rest, and `ZONE_MOVABLE`'s size is derived from boot
parameters or hotplug policy. The function `free_area_init()` (called from the arch setup
path) takes the per-node PFN ranges and zone limits and builds the `pglist_data`/`zone`
skeletons, computing `spanned_pages` and `present_pages` for each.

### 4.4 Building the `struct page` array (sparsemem)

With node and zone extents known, the kernel allocates the **page descriptor array** via
`memblock`. Under SPARSEMEM_VMEMMAP this means populating the `vmemmap` region: for each
present memory **section**, allocate physical backing (from `memblock`) for that section's
`struct page` descriptors and map it into the `vmemmap` virtual range, then initialize each
descriptor (`memmap_init`) — marking pages `PG_reserved` initially. This is the step that
makes `pfn_to_page()` work. On large machines this array is gigabytes; computing it lazily and
only for present sections is exactly why sparsemem exists.

### 4.5 Handover to the buddy allocator

Finally the system "turns on" the real allocator. `mem_init()` (arch-specific) calls
`memblock_free_all()`, which walks every region that is in `memblock.memory` but **not** in
`memblock.reserved` and releases those frames into the buddy allocator by clearing their
`PG_reserved` flag and freeing them at the appropriate order (`__free_pages_core`). At this
moment the buddy free lists become populated, the zone `managed_pages` counters are set, and
`memblock` is effectively retired (its bookkeeping may be discarded). The watermarks are
computed from the now-known managed page counts, and the per-CPU page lists are set up. (The
per-node `kswapd`/`kcompactd` kernel threads are started slightly later in boot, during the
init-call phase, not at this exact handover instant.)

After this point allocations go through the normal `alloc_pages()` path; the boot allocator is
gone. The kernel command line can still influence the result (`mem=` to cap RAM, `memmap=` to
hand-edit the e820 map, `numa=`, `movablecore=`/`kernelcore=` to size `ZONE_MOVABLE`,
`hugepagesz`/`hugepages=` to pre-reserve huge pages while contiguous memory is still
plentiful).

---

<a name="5-page-allocation"></a>
## 5. Page allocation: the buddy allocator and its surroundings

### 5.1 The binary buddy algorithm

The **buddy allocator** is the kernel's physical page allocator. Within each zone it keeps,
for every order *k* from 0 to `MAX_PAGE_ORDER`, a list of free **blocks** of exactly 2ᵏ
contiguous, naturally-aligned pages (`free_area[k]`). The defining trick is the **buddy**
relationship: a block of order *k* starting at PFN *p* has a unique buddy at PFN
`p XOR (1 << k)` — the adjacent aligned block of the same size. Two facts make the algorithm
fast:

- **Allocation by splitting.** To satisfy a request for order *k*, the allocator looks at
  `free_area[k]`. If it's empty, it goes up to the smallest order *j > k* that has a free
  block, removes one block, and repeatedly **splits** it in half, putting the unused buddy
  halves back on the lower free lists, until it has a block of exactly order *k*. So a request
  for one page (order 0) when only an order-3 block is free yields one page and deposits
  blocks of order 0, 1, and 2 back onto their lists.
- **Freeing by coalescing.** When a block of order *k* is freed, the allocator checks whether
  its buddy (`p XOR (1<<k)`) is also free and of the same order. If so, the two are **merged**
  into one order-(k+1) block, and the check repeats upward. This is what keeps fragmentation
  in check: adjacent frees recombine into large contiguous blocks automatically. The buddy's
  state is checked cheaply via the buddy page's flags and `_refcount`/order bookkeeping.

Computing the buddy with a single XOR, and merging in O(log) steps, is what makes the buddy
system the right low-level primitive: it provides physically contiguous, aligned blocks (which
DMA and huge pages need) with bounded external fragmentation.

### 5.2 Migratetypes and anti-fragmentation

A pure buddy system still fragments over time: a single unmovable allocation stranded in the
middle of an otherwise-free large region prevents that region from ever coalescing into a high
order. Linux mitigates this with **migratetype-based grouping**. Each **pageblock** has a
migratetype, and the free lists are split *per migratetype*
(`free_area[k].free_list[MIGRATE_TYPES]`). A pageblock is `pageblock_order` pages; on a
typical x86-64 build with huge pages enabled (`CONFIG_HUGETLB_PAGE`, the usual case) that is
the **PMD huge-page order — 2 MiB**, not `MAX_PAGE_ORDER`. The pageblock only equals
`MAX_PAGE_ORDER` (4 MiB) when huge pages are configured out. The 6.8 migratetypes are:

- **`MIGRATE_UNMOVABLE`** — kernel data that cannot be relocated (most slab, page tables,
  pinned memory).
- **`MIGRATE_MOVABLE`** — user pages and page cache that *can* be migrated (Section 8), so
  these blocks stay defragmentable.
- **`MIGRATE_RECLAIMABLE`** — memory that can't be moved but can be freed under pressure (some
  reclaimable slab caches, e.g. dentries/inodes).
- **`MIGRATE_HIGHATOMIC`** — a small reserve kept for high-order atomic allocations that can't
  sleep or reclaim.
- **`MIGRATE_CMA`** — Contiguous Memory Allocator regions, which behave like movable memory but
  can be turned into guaranteed large contiguous allocations on demand (used by, e.g., camera/
  GPU drivers).
- **`MIGRATE_ISOLATE`** — a transient type marking a pageblock that is being isolated (for
  hot-unplug, CMA, or compaction) so nothing new is allocated from it.

The idea is **segregation by mobility**: keep unmovable allocations clustered together so that
movable regions stay contiguous and can be compacted into huge pages or freed for hot-unplug.
When a zone runs low on a given migratetype it **steals** whole pageblocks from another type
according to a fixed `fallbacks[][]` preference order (in `mm/page_alloc.c`), preferring to
steal the largest available block to avoid scattering. This whole anti-fragmentation scheme
postdates Gorman's book and is central to why modern systems can reliably allocate transparent
huge pages.

### 5.3 GFP flags: telling the allocator what you can tolerate

Every allocation passes **GFP flags** (`gfp_t`, "get free pages") that encode the constraints
and freedoms of the request. They split into three groups: a **zone modifier** (which zones
are acceptable), **mobility/placement** hints, and an **action/watermark** group (whether the
caller may sleep, do I/O, dip into reserves, trigger reclaim, etc.). The common composite
flags:

- **`GFP_KERNEL`** — the default for kernel allocations that run in process context: may sleep,
  may perform I/O and filesystem writeback to reclaim, may invoke direct reclaim and the OOM
  killer. The flexible, "I can wait" request.
- **`GFP_ATOMIC`** — for code that cannot sleep (interrupt handlers, holding a spinlock): the
  allocator may **not** reclaim or block, but in exchange it is allowed to dip into emergency
  reserves below the low watermark. High-order `GFP_ATOMIC` requests are fragile and
  discouraged.
- **`GFP_NOWAIT`** — like atomic but without access to emergency reserves; fails fast rather
  than blocking.
- **`GFP_NOFS` / `GFP_NOIO`** — may sleep, but must not recurse into the filesystem
  (`NOFS`) or into any I/O (`NOIO`); used to avoid deadlocks when the caller is *itself* in the
  writeback/I/O path.
- **`GFP_USER`, `GFP_HIGHUSER`, `GFP_HIGHUSER_MOVABLE`** — for user-space-backing pages, the
  last of which marks the pages movable so they land in movable pageblocks.

Important single-bit modifiers include `__GFP_ZERO` (return a zeroed page), `__GFP_MOVABLE`
(this allocation is migratable), `__GFP_THISNODE` (do not fall back off-node),
`__GFP_NORETRY`/`__GFP_RETRY_MAYFAIL` (tune how hard the slow path tries before failing), and
`__GFP_NOFAIL` (loop forever rather than return NULL — used sparingly). The flags are the
contract that lets one allocator serve interrupt context and user page faults alike.

### 5.4 Watermarks and the fast path vs. slow path

Each zone carries three **watermarks**, scaled from the zone's managed page count:
`WMARK_MIN < WMARK_LOW < WMARK_HIGH`. They form the control loop for reclaim:

- Above **high**: plenty of memory; nobody reclaims.
- Crossing below **low**: the zone is getting tight, so `kswapd` (the per-node background
  reclaim thread) wakes up and reclaims **asynchronously** until the zone is back above
  **high**.
- Reaching **min**: only the most privileged allocations (`GFP_ATOMIC`, `PF_MEMALLOC`
  contexts) may consume the last reserves; ordinary allocations must reclaim first.

A normal allocation flows like this. `alloc_pages()` / `__alloc_pages()` (in `mm/page_alloc.c`)
first tries the **fast path**, `get_page_from_freelist()`, which walks the zonelist and, at
each acceptable zone, checks the watermark (`zone_watermark_ok()`); if a zone is above the
relevant watermark it pulls a block of the requested order/migratetype — for a single page this
almost always comes from the **per-CPU page list** without touching the zone lock. If the fast
path fails (every zone is below its watermark), the allocator enters the **slow path**,
`__alloc_pages_slowpath()`, which escalates step by step:

1. Wake `kswapd` on the candidate zones.
2. Retry the freelist with **lowered** watermarks (allowing the request to dip a bit).
3. For costly/high-order requests, try **direct compaction** (Section 8) to assemble a
   contiguous block.
4. Perform **direct reclaim** — the allocating thread itself runs reclaim synchronously to free
   pages, then retries.
5. If everything fails and the GFP flags allow it, invoke the **OOM killer** to free memory by
   terminating a process, then retry.
6. Eventually give up and return `NULL` (unless `__GFP_NOFAIL`).

This staged escalation — cheap and lock-free when memory is plentiful, progressively more
aggressive and more willing to block as it gets scarce — is the heart of how Linux trades
latency for success under pressure.

### 5.5 Per-CPU page lists (PCP)

Because single-page allocation and free is by far the hottest path, each zone keeps a
**per-CPU cache** of free pages (`struct per_cpu_pages`). Frees of order-0 (and small-order)
pages go onto the local CPU's list; allocations are served from it. This avoids the zone
spinlock and the cross-CPU cache-line bouncing it would cause, and it improves cache locality
(a just-freed page is likely still warm in this CPU's cache). The lists are bounded; when they
grow past a high-water batch they spill back to the buddy free lists, and when empty they
refill in a batch. This is a pure performance layer on top of the buddy allocator — the pages
are still buddy pages, just temporarily parked per-CPU.

### 5.6 Above the buddy allocator

Most kernel code does not call the buddy allocator directly. The layers on top:

- **SLUB** (`kmalloc`, `kmem_cache_alloc`) for sub-page objects — it allocates whole pages from
  buddy and subdivides them into **object caches**, each a pool of fixed-size objects of one
  type (e.g. a cache for `task_struct`s, one for inodes, one for dentries), with per-CPU fast
  paths for lock-free allocation of the hot objects. SLUB is where most small kernel structures
  live, and some of its caches (notably the **dentry and inode caches**) hold *reclaimable*
  objects — which is why reclaim can shrink them under pressure via **shrinkers** (Section 7.6).
  SLUB is the only slab allocator in 6.8; the older SLAB and SLOB implementations have been
  removed.
- **`vmalloc`** for large, virtually-contiguous but **physically scattered** allocations — it
  grabs individual pages from buddy and stitches them together with fresh page-table entries in
  the `vmalloc` virtual region. Useful when you need a big buffer but contiguous physical memory
  is unavailable or unnecessary.
- **`alloc_pages` / `folio_alloc`** for whole pages/folios, used directly by the page fault
  handler, the page cache, and anyone needing page-granular memory.

---

<a name="6-the-page-cache"></a>
## 6. The page cache (the modern "file buffer cache")

### 6.1 One unified cache, not two

Older Unix systems (and early Linux) had a *separate* **buffer cache** for raw disk blocks and
a **page cache** for file contents, which led to double-caching and coherence headaches. Modern
Linux — already true in the book's 2.6 era and more so now — has **one unified page cache**.
File data is cached in page-sized (now **folio**-sized) units keyed by *(file, offset)*, and the
old "buffer cache" survives only as a **view** onto page-cache memory: `struct buffer_head`
objects describe individual disk blocks *within* a cached folio, used by filesystems that do
block-level I/O (and for filesystem metadata). So when this guide says "file buffer cache," in
6.8 that means **the page cache**, with buffer_heads as an optional per-block overlay.

### 6.2 `address_space`: the core data structure

Every cacheable object — a regular file's contents, a block device, a shared memory segment —
has an **`struct address_space`** (`include/linux/fs.h`), usually embedded in the file's inode.
It is the heart of the page cache:

- **`i_pages`** — an **XArray** (`struct xarray`) mapping page offsets (in folio-index units) to
  the folios that cache them. The XArray replaced the older **radix tree** the book describes;
  it is functionally a radix tree with a cleaner API and built-in locking, and it also stores
  special **shadow/value entries** (Section 7.4) inline. This is the structure that answers "is
  offset N of this file resident, and if so where?"
- **`a_ops`** — the `address_space_operations` vtable: `read_folio`, `writepage`/`writepages`,
  `dirty_folio`, `invalidate_folio`, `release_folio`, `direct_IO`, `migrate_folio`, etc. This is
  how the generic page-cache code calls into a *specific* filesystem to fill or write back a
  folio.
- **`host`** — back-pointer to the owning inode.
- Counters and flags: number of cached pages, writeback/dirty tags (stored as XArray marks so
  the kernel can quickly iterate just the dirty or under-writeback folios), GFP mask for
  allocations, etc.

To find a file page, the kernel hashes nothing — it indexes `mapping->i_pages` by the folio
index. A hit returns the resident folio; a miss triggers a read.

### 6.3 Reads, readahead, and the fault path

When a process reads a file (via `read()`/`pread()` or by faulting on an `mmap`), the generic
path (`filemap_read`, `filemap_fault` in `mm/filemap.c`) looks up the folio in the
`address_space`. On a **hit**, it copies/maps the cached data — no I/O. On a **miss**, it
allocates a folio, inserts it into the XArray (locked, marked not-up-to-date), and calls the
filesystem's `read_folio` to populate it from storage; when I/O completes the folio is marked
`uptodate` and unlocked.

Crucially, the kernel does **readahead**: on detecting sequential access it reads *ahead* of the
current position, allocating and issuing I/O for a window of upcoming folios so later reads hit
in cache. The readahead machinery (`mm/readahead.c`, `struct readahead_control`, the
`file_ra_state` per open file) grows the window on continued sequential hits and shrinks or
disables it on random access. With **large folios**, the cache can store a single multi-page
folio per cache entry, reducing per-page overhead and improving I/O efficiency for large files.

### 6.4 Writes, dirty tracking, and writeback

A write into a cached file page copies data into the folio and marks it **dirty**
(`folio_mark_dirty`, setting `PG_dirty` and tagging the folio dirty in the XArray, and marking
the owning inode dirty). The write returns immediately — this is **write-back caching**; the
data is not yet on disk. Persisting it is the job of **writeback**:

- Dirty data is flushed by per-backing-device (**per-bdi**) **flusher threads** (the
  `writeback` workqueue / `wb_workfn`), which walk dirty inodes and call `writepages` to issue
  I/O. There is no longer a single `pdflush`/`bdflush` thread as in the book; writeback is
  per-device so a slow disk can't stall flushing on a fast one.
- Flushing is triggered by **time** (data older than `dirty_expire_centisecs`), by **pressure**
  (dirty memory exceeding `dirty_background_ratio`, which kicks off background writeback, or
  `dirty_ratio`, at which *writing processes themselves* are throttled in
  `balance_dirty_pages` until they've cleaned enough), and by explicit `fsync`/`sync`.
- `balance_dirty_pages()` implements **dirty throttling**: it estimates each writer's fair share
  of writeback bandwidth and pauses fast writers so dirty memory can't grow unbounded and
  overwhelm reclaim. This feedback controller is far more sophisticated than the book's simple
  thresholds.

The result is the classic trade-off managed automatically: writes are fast (cached) but bounded
(throttled), and data reaches disk in efficient batches.

### 6.5 Why the page cache and the allocator are intertwined

Page-cache folios are ordinary `ZONE_NORMAL`/`MOVABLE` frames on the **LRU lists** (Section 7).
Clean cache pages are essentially free memory the kernel is *borrowing* for caching — they can
be dropped instantly under pressure (just remove from the XArray and free). Dirty ones must be
written back first. This is why "free" memory on a healthy Linux box is usually small while
"available" memory is large: most RAM is page cache that can be reclaimed on demand. The
allocator's watermarks and the reclaim machinery treat clean page cache as the first and
cheapest thing to evict.

---

<a name="7-page-reclaim-and-opt"></a>
## 7. Page reclaim, the OPT ideal, and the LRU approximations

> **A note on the two ideas in this requested topic.** "Page replacement (the OPT ideal)" and
> "page migration" are *different* mechanisms that are easy to conflate. **Replacement /
> reclaim** (this section) decides *which resident page to evict* to free a frame. **Migration**
> (Section 8) *relocates a page's contents to a different frame* without evicting it at all.
> OPT belongs to the first; migration is the second. Both requested items are covered — here
> and in the next section respectively.

### 7.1 The problem and the unreachable ideal (OPT)

When memory is exhausted and a new allocation needs a frame, the kernel must **evict** a
resident page to free one. The theoretically optimal choice is **OPT** (also called **MIN** or
**Belady's algorithm**): evict the page whose *next* use is **furthest in the future**. OPT
provably minimizes the number of page faults. But it is **unimplementable online** because it
requires knowledge of the future reference stream. OPT is therefore a *yardstick* — the best any
replacement policy could do — not something a real kernel can run. Every practical policy,
Linux's included, is an **approximation of OPT** that uses the *past* (recency and frequency of
reference) to predict the future, on the **locality** assumption that recently/frequently used
pages will be used again soon.

The hardware gives the kernel only a weak signal to work with: each page-table entry has an
**accessed (A) bit** the CPU sets when the page is referenced and a **dirty (D) bit** it sets on
write (Section 9.2 covers where these bits sit in the PTE). The kernel can read and clear these
bits but gets no timestamps and no frequency counts —
so all of Linux's reclaim cleverness is about extracting a good recency/frequency estimate from
those single bits sampled over time. This is the classic "clock"/"second chance" idea
generalized.

### 7.2 The classic active/inactive two-list LRU

The long-standing Linux approximation (the one closest to Gorman's description, still present in
6.8 when the multigenerational LRU is disabled) keeps pages on **LRU lists** held per-node in the
`lruvec`, split by type and activity:

- `LRU_INACTIVE_ANON`, `LRU_ACTIVE_ANON` — anonymous (process heap/stack) pages.
- `LRU_INACTIVE_FILE`, `LRU_ACTIVE_FILE` — file-backed (page cache) pages.
- `LRU_UNEVICTABLE` — pages that must not be reclaimed, kept off the scan entirely as an
  optimization. A page is unevictable when userspace has **`mlock`**ed it (pinned it resident
  with `mlock`/`mlockall`, e.g. a process guaranteeing a buffer never faults), when it belongs
  to a non-swap-backed filesystem like `ramfs`, or when it is otherwise pinned. Moving these
  off the active/inactive lists means reclaim never wastes time scanning pages it can't free.

Separating **anon** from **file** matters because reclaiming a file page may be free (drop a
clean cache page) while reclaiming an anon page always costs a **swap** write. Separating
**active** from **inactive** implements a two-chance scheme: newly referenced pages start on the
inactive list; if referenced again while there, they are **promoted** to the active list; the
**active list is not scanned for eviction** until the inactive list is too small. Reclaim
(`shrink_lruvec`/`shrink_list`) scans the **inactive** list from the cold end, and for each page
consults the accessed bit (across all the page's mappings, via the **reverse mapping**): if it
was referenced, give it a second chance (rotate/promote); if not, evict it (drop if clean, swap
or write back if dirty). The relative pressure on anon vs. file is tuned by a **swappiness**
knob and by cost feedback. This is recognizably "LRU approximation by sampling the accessed bit"
— a clock algorithm with two hands and an anon/file split.

### 7.3 Reverse mapping (rmap): finding every PTE for a page

To evict a physical page the kernel must unmap it from **every** address space that maps it,
which means finding all the PTEs pointing at that frame — the **reverse mapping** problem.
Linux's **rmap** (`mm/rmap.c`) solves it: for file pages, the `address_space` plus an interval
tree of VMAs (`i_mmap`) yields every mapping of a given file offset; for anonymous pages, an
**anon_vma** structure chains together the VMAs (including those created by `fork`) that may map
the page. With rmap, `try_to_unmap()` can walk to each PTE, check/clear the accessed bit, flush
the TLB, and (for dirty pages) arrange writeback or swap. Rmap is what makes accessed-bit
sampling and eviction possible across shared pages; it is also the foundation for migration
(Section 8), which must rewrite every PTE to point at the page's new location.

### 7.4 Refault detection and workingset

A subtle failure mode of a plain two-list LRU is **thrashing**: a working set slightly larger
than the inactive list churns pages in and out, and the policy can't tell a one-off scan
(stream once, never reuse) from a working set under pressure. Linux 6.8 addresses this with
**workingset / refault detection** (`mm/workingset.c`). When a page is evicted, the kernel
leaves a **shadow entry** in the XArray recording *roughly when* (in terms of LRU "eviction
distance") it was evicted. If that page is read back in soon — a **refault** — the kernel
compares the eviction distance to the size of the active list to decide whether the page was
wrongly evicted, and if so it **grows the protection** for that class of pages (e.g. activate
the refaulted page immediately). This gives the policy a memory of its own recent mistakes and
lets it adapt the anon/file balance and active/inactive sizing to the real workload — a
significant refinement over the book-era algorithm.

### 7.5 The multi-generational LRU (MGLRU)

Linux 6.8 ships the **multi-generational LRU** (`CONFIG_LRU_GEN`, `mm/vmscan.c` plus the
`lru_gen_*` machinery), a newer reclaim framework (mergeable/enable-able since 6.1) that can
replace the active/inactive lists. Instead of two activity levels it organizes each `lruvec`
into multiple **generations** — a sliding window of up to `MAX_NR_GENS` (4) — where the
**youngest** generation holds recently accessed pages and the **oldest** is the eviction
frontier:

- **Aging** advances the generation counter and ages pages by scanning page tables (and using
  the look-around heuristic `lru_gen_look_around` to harvest accessed bits from *neighboring*
  PTEs cheaply, exploiting spatial locality) rather than walking the global LRU list and using
  rmap for every page. This makes building the recency estimate much cheaper on large memories.
- **Eviction** takes pages from the oldest generation.
- Pages get a more graduated notion of "how recently/often used" than the binary active/inactive
  split, and the design tracks anon and file pages with per-generation, per-zone lists
  (`lru_gen_folio`).

The practical wins are lower CPU cost to identify cold pages (page-table scanning + look-around
instead of pervasive rmap walks) and better decisions under pressure, especially for large
workloads and containers. MGLRU is exposed via `/sys/kernel/mm/lru_gen/`. Either way — classic
two-list or MGLRU — the **goal is identical**: cheaply approximate OPT by inferring future use
from sampled recency/frequency.

### 7.6 Who runs reclaim, and the OOM killer

Reclaim runs in two contexts. **`kswapd`** (one kernel thread per node) wakes when a zone falls
below its low watermark and reclaims in the background up to the high watermark, keeping
allocations off the slow path. **Direct reclaim** happens *inline* in an allocating thread when
the fast path fails and `kswapd` can't keep up — the thread runs `shrink_node` itself before
retrying, which is why a memory-starved allocation can block. Reclaim also drives **shrinkers**
(`shrink_slab`) to reclaim non-page caches (dentry/inode caches and other registered slab
caches) proportionally. If reclaim cannot free enough and the allocation can't fail, the
**OOM killer** (`mm/oom_kill.c`) selects a process (scored by `oom_score`, tunable via
`oom_score_adj`) and kills it to release memory — the last resort.

### 7.7 Swap, and per-cgroup memory control (memcg)

**Swap** is what makes *anonymous* pages reclaimable. A clean file page can be dropped for
free (its data is still on disk), but an anonymous page — heap, stack, anonymous `mmap` — has
no backing store, so before its frame can be reused its contents must be written somewhere.
That somewhere is a **swap area**: a swap partition or swap file, registered with `swapon` and
managed in `mm/swapfile.c`. Each swap area is divided into page-sized **slots**.

The mechanism hinges on a clever reuse of the page table. When reclaim swaps a page out, it
writes the page to a free swap slot and replaces the page's **PTE** with a **swap entry**
(`swp_entry_t`) — a value, encoded into the same 64 bits, that is **not present** (so any
access faults) but encodes *which swap area and slot* hold the data. So the PTE itself is the
record of where the page went. On the next access the not-present PTE triggers a fault; the
fault handler reads the swap entry, allocates a fresh frame, reads the data back from the
slot (a **swap-in**, or "major fault"), and reinstalls a normal present PTE. A **swap cache**
(`mm/swap_state.c`) sits in between so that a page shared by several processes isn't read in
or written out multiple times, and so an in-flight swap operation has a stable home. A key
consequence: **with no swap device configured, anonymous pages are effectively unevictable** —
the kernel can only reclaim file pages, and under pressure goes more quickly to the OOM
killer. The `swappiness` knob (`/proc/sys/vm/swappiness`) tunes how aggressively the kernel
prefers swapping anon vs. reclaiming file pages.

**Per-cgroup memory control (memcg).** Everything in this section so far describes *global*
reclaim. On a modern system memory is also managed per **control group** (cgroup v2; the
memory controller, `mm/memcontrol.c`). Each cgroup can have `memory.max` (a hard limit),
`memory.high` (a throttling threshold), and `memory.min`/`memory.low` (protection floors).
When a cgroup approaches its limit, the kernel runs reclaim **scoped to that cgroup's pages**
— which is exactly why the LRU lists are per-(cgroup, node) `lruvec`s (Section 3.1) rather
than purely per-node: reclaim must be able to walk just one cgroup's pages. If a cgroup can't
stay under its hard limit even after reclaim, a **cgroup-scoped OOM kill** targets a process
*within that cgroup*, without disturbing the rest of the system. This is the foundation of
container memory isolation, and it means "how much memory is available" is, in 6.8, a
per-cgroup question as much as a global one.

---

<a name="8-page-migration-and-compaction"></a>
## 8. Page migration and compaction

### 8.1 What migration is

**Page migration** (`mm/migrate.c`, `migrate_pages()`) physically relocates the contents of a
page from one frame to another while keeping it transparently usable by everyone mapping it. The
mechanics: isolate the source page from its LRU list; take the locks and **unmap** it from every
mapping using rmap (so no CPU can touch it mid-move, and faults block); copy the page contents
(and its flags/state) to a freshly allocated destination frame; rewrite every PTE and the
page-cache XArray entry to point at the new frame (`move_to_new_folio`, the filesystem's
`migrate_folio` operation for cache pages); then unlock and free the old frame. Because every
reference is found via rmap and the page is locked throughout, the move is invisible to user
space — pointers and mappings keep working, now resolving to the new physical location.

Migration is only possible for **movable** pages (user/anon pages, page cache, anything whose
filesystem provides a `migrate_folio` op). Pinned kernel memory, page tables, and pages under
`get_user_pages(..., FOLL_PIN)` cannot be moved — which is exactly why the migratetype
segregation of Section 5.2 exists: to keep movable pages clustered so large movable regions stay
relocatable.

### 8.2 What migration is used for

Migration is a mechanism with several clients:

- **Memory compaction** (defragmentation) — see 8.3.
- **NUMA balancing** — moving a task's pages to the node where it runs (8.4).
- **Memory hot-unplug** — before removing a memory bank, every movable page on it is migrated
  elsewhere; this is the original reason `ZONE_MOVABLE` and migratetypes exist.
- **CMA** — assembling a large physically-contiguous region for a device by migrating away the
  movable pages currently occupying a reserved CMA range.
- **`move_pages()` syscall / `MPOL_*`** — explicit userspace-directed placement.
- **Tiered memory / demotion** — on systems with slow memory tiers (e.g. CXL/PMEM), cold pages
  can be **demoted** to a slower node instead of swapped, and hot pages promoted back; the
  `WMARK_PROMO` watermark and NUMA-balancing promotion paths participate in this.

### 8.3 Compaction: manufacturing contiguity

High-order allocations (transparent huge pages, large DMA buffers, large folios) need
physically contiguous, aligned blocks that a fragmented zone may not have on its free lists even
when total free memory is ample. **Compaction** (`mm/compaction.c`) creates contiguity by
migration. It runs **two scanners** that move toward each other within a zone:

- A **migration scanner** walks from the bottom of the zone upward, collecting *in-use movable*
  pages.
- A **free scanner** walks from the top downward, collecting *free* pages to serve as migration
  destinations.

It then migrates the movable pages from the low end into the free slots at the high end,
effectively sweeping used movable pages toward one side and coalescing free space into large
contiguous buddy blocks on the other. When the scanners meet, the zone has been compacted.
Compaction is invoked by `kcompactd` (a per-node background thread), **directly** from the
allocator slow path when a high-order request fails, and explicitly via
`/proc/sys/vm/compact_memory`. It is the supply side that makes transparent huge pages and other
high-order allocations succeed on a long-running, fragmented system — and it depends entirely on
migration plus the movable-pageblock segregation.

### 8.4 Automatic NUMA balancing

To improve locality without application awareness, the kernel runs **automatic NUMA balancing**
(`mm/`, scheduler-integrated). Periodically it removes the present bit / sets a special "NUMA
hinting" protection on a sample of a task's pages, so the next access **faults**. The fault
handler (`do_numa_page`) records *which node* the accessing CPU is on relative to where the page
lives. If a page is consistently accessed from a remote node, it is **migrated** toward the
accessing CPU's node; the scheduler conversely tries to keep tasks near their memory. This
"sample by faulting, then migrate" loop gradually co-locates each task with its working set,
trading a controlled number of minor faults for substantially better average memory latency on
NUMA hardware.

---

<a name="9-page-tables"></a>
## 9. Page tables: the x86-64 multi-level walk

### 9.1 Virtual address translation, level by level

On x86-64, the MMU translates a virtual address to a physical one by walking a **multi-level
tree of page tables** (a radix tree in the generic sense — unrelated to the page cache's
former radix tree from Section 6.2) rooted in the **CR3** register, which holds the physical
address of the top-level table for the currently running process. With standard 4 KiB pages there are **four** levels
(48-bit virtual addresses, 256 TiB) or, on hardware and kernels with **5-level paging**
(`CONFIG_X86_5LEVEL`, the "LA57" feature), **five** levels (57-bit virtual addresses, 128 PiB).
Linux names the levels, top to bottom:

- **PGD** — Page Global Directory (the CR3 root).
- **P4D** — fourth-level directory (only meaningful with 5-level paging; *folded away* under
  4-level — see 9.3).
- **PUD** — Page Upper Directory.
- **PMD** — Page Middle Directory.
- **PTE** — Page Table Entry (the leaf, pointing at the actual 4 KiB frame).

A 48-bit address is sliced into four **9-bit indices** (one per level, since each table holds
2⁹ = 512 entries of 8 bytes, filling exactly one 4 KiB page) plus a **12-bit page offset**:
`[PGD:9][PUD:9][PMD:9][PTE:9][offset:12]`. The MMU uses each 9-bit slice to index the table at
that level, reads the entry to get the physical address of the next-level table, and repeats,
until the PTE yields the physical frame; the 12-bit offset selects the byte within it. A
5-level walk inserts the P4D index and uses a 57-bit address. Each level's table is itself one
physical page, allocated from the buddy allocator.

### 9.2 Page-table entries and their bits

Each entry (`pgd_t`/`p4d_t`/`pud_t`/`pmd_t`/`pte_t` — opaque arch types accessed only through
accessor macros) is a 64-bit value: the upper/middle bits hold the physical frame number of the
next table or final page, and the low and top bits hold **flags** the hardware and kernel use:

- **Present (P)** — if clear, the entry is not backed; any access **faults** (this is how Linux
  implements demand paging, swapped-out pages, and NUMA hinting — a not-present or specially
  marked entry traps into `do_page_fault`).
- **R/W** — writable or read-only (read-only is how **copy-on-write** after `fork` is enforced:
  a write faults, the handler copies the page and grants write access).
- **U/S** — user or supervisor (kernel-only) page.
- **A (accessed)** and **D (dirty)** — set by hardware on reference/write; sampled and cleared by
  reclaim (Section 7).
- **PS (page size)** — at the PMD/PUD level, set means this entry is a **huge page** leaf (2 MiB
  at PMD, 1 GiB at PUD) rather than a pointer to a lower table.
- **G (global)** — the translation survives TLB flushes on CR3 reload (used for kernel mappings).
- **NX (no-execute)** — the top bit; marks the region non-executable (W^X enforcement).

Linux manipulates these only through architecture-neutral accessors — `pte_present`,
`pte_write`, `pte_dirty`, `pte_mkwrite`, `set_pte_at`, `pmd_large`, `mk_pte`, and the page-table
walk helpers `pgd_offset`/`p4d_offset`/`pud_offset`/`pmd_offset`/`pte_offset_map` — so that
generic mm code never embeds x86 bit layouts. The same generic code therefore runs unchanged on
ARM64, RISC-V, etc., which define the same accessors over their own hardware formats.

### 9.3 Folding: one source for 2-, 3-, 4-, and 5-level tables

Linux's mm code is written *once* against the **five-level** abstraction (PGD→P4D→PUD→PMD→PTE),
even on hardware with fewer levels. The trick is **page-table folding**: on a configuration with
*N* levels, the unused upper levels are made to **collapse** — their "offset" accessor simply
returns its input pointer and the level appears to have a single entry. The headers
`include/asm-generic/pgtable-nop4d.h`, `-nopud.h`, and `-nopmd.h` implement this. So under
4-level paging the **P4D level is folded into the PGD** (`p4d_offset` is a no-op), and generic
code that walks all five levels compiles down to a four-level walk with the P4D step optimized
away. This is why you can read `mm/` code that always mentions P4D yet runs correctly on a CPU
that has no such level — the abstraction folds to fit the hardware, and 6.8 supports 5-level
paging without a separate code path.

### 9.4 The TLB and shootdowns

Walking four or five levels of tables for every memory access would be ruinous, so the CPU
caches recent translations in the **TLB** (Translation Lookaside Buffer). The TLB is a hardware
cache the kernel cannot read, only **invalidate**, which creates a coherence duty: whenever the
kernel changes a page-table entry that may be cached (unmapping a page, changing protections,
migrating, reclaiming), it must invalidate the stale TLB entry — `INVLPG` for a single address,
or a full flush via a CR3 reload. On a multiprocessor, *other* CPUs may also have cached the old
translation, so the kernel must perform a **TLB shootdown**: send an inter-processor interrupt
(IPI) to the relevant CPUs and have each invalidate the entry, the initiator waiting until all
acknowledge before reusing the freed frame. Shootdowns are expensive, so the mm code batches
them and tracks which CPUs ever ran a given `mm` (`mm_cpumask`) to avoid disturbing CPUs that
never used the mapping. **PCID/ASID** tagging lets the hardware keep translations for multiple
address spaces in the TLB simultaneously, so a context switch need not flush everything.

### 9.5 The kernel's own address space and KPTI

Each process's page tables map *both* the user portion (the lower half of the canonical address
space, private per process) and the kernel portion (the upper half, shared across all
processes). The kernel half includes the **direct/linear map** (all physical RAM mapped
contiguously, so the kernel can reach any frame by a simple `__va`/`__pa` offset — the modern
replacement for the highmem gymnastics in Gorman's book), the **vmemmap** region (the `struct
page` array, Section 2), the **vmalloc** region, and the kernel text/modules. Because the kernel
mappings are identical in every process, switching processes only changes the user half.

After Meltdown, x86-64 added **KPTI** (Kernel Page-Table Isolation): each process actually keeps
**two** PGDs — one with the full kernel mapping used while running in the kernel, and a minimal
one (just enough trampoline/entry code) used while running in user space — so that speculative
user-mode accesses cannot reach kernel data that isn't mapped at all. Switching between them
happens on kernel entry/exit. This is invisible to the mm abstractions but is part of how 6.8
page tables are actually laid out on x86-64.

### 9.6 Huge pages

Mapping large regions with 4 KiB PTEs wastes TLB entries and page-table memory. Linux supports
**huge pages** by making a PMD entry (2 MiB) or PUD entry (1 GiB) a **leaf** (the PS bit), so one
TLB entry covers the whole range. There are two flavors: **hugetlbfs**, explicitly reserved huge
pages requested by applications (databases, VMs) via a special filesystem/`mmap` flags, drawn
from a pre-reserved pool; and **Transparent Huge Pages (THP)**, where the kernel *automatically*
backs suitable anonymous (and, increasingly, file) regions with huge pages and a background
thread (**`khugepaged`**) *collapses* eligible runs of base pages into huge pages over time.
THP's supply depends directly on the compaction and anti-fragmentation machinery (Sections 5.2,
8.3): without large contiguous free blocks, there is nothing to map as a huge page. When a huge
page must be partially unmapped or swapped, it is **split** back into base pages.

---

<a name="10-address-spaces-and-faults"></a>
## 10. Virtual address spaces: VMAs and the page fault handler

The page tables of Section 9 are the *hardware* view of a process's address space. The
*kernel's* view — the bookkeeping it uses to decide what each address means and to fill the
tables in lazily — is a separate set of structures. This section covers them and the **page
fault handler**, which is the connective tissue that ties almost every subsystem in this guide
together.

### 10.1 `mm_struct` and VMAs

Each process's address space is described by a **`struct mm_struct`** (`include/linux/
mm_types.h`): it owns the top-level page-table pointer (`pgd`), assorted counters and limits,
and — crucially — the set of **memory regions** that make up the address space. A region is a
**`struct vm_area_struct`** (a **VMA**): a contiguous run of virtual addresses that share the
same backing and permissions. One VMA might describe the read-only executable mapping of a
program's text, another the read/write data segment, another an anonymous heap region, another
a file `mmap`ed into the process, another the stack. Each VMA records its start/end addresses,
its protection flags (`VM_READ`/`VM_WRITE`/`VM_EXEC`), whether it is shared or private, and —
for file mappings — which file and offset it backs.

A process can have thousands of VMAs, and the fault path must, on **every** fault, find the
VMA containing the faulting address *fast*. In 6.8 the VMAs of an `mm` are indexed by a
**maple tree** (`struct maple_tree`), a modern B-tree-like structure optimized for storing
non-overlapping ranges with good cache behavior and support for lock-light lookups. It
replaced the red-black tree (plus a separate linked list) that older kernels used for this
job. The lookup `find_vma(mm, addr)` walks the maple tree to the VMA covering (or following)
an address. Importantly, a VMA describes *intent* — "addresses X..Y are a private writable
anonymous region" — and carries **no physical memory by itself**; physical frames and page-
table entries are created lazily, on demand, by the fault handler.

### 10.2 The page fault handler and its cases

When the MMU cannot complete a translation — the entry is not present, or the access violates
the entry's permissions — it raises a **page fault**, trapping into the kernel at
`do_page_fault` (`arch/x86/mm/fault.c`) and then the architecture-neutral `handle_mm_fault`
(`mm/memory.c`). The handler first finds the VMA for the faulting address. **No VMA, or an
access the VMA's flags forbid** (e.g. writing a read-only region) is a genuine error — a
**segmentation fault** (`SIGSEGV`) for user space, or an oops/fixup for the kernel. Otherwise
the fault is *expected*, and the handler's job is to make the access succeed by populating the
page tables. The major legitimate cases:

- **Demand-zero (anonymous) fault.** The VMA is anonymous and nothing is mapped yet. On a read,
  the kernel can cheat by pointing the PTE at a single shared, read-only **zero page** (one
  system-wide frame full of zeros), so countless never-written pages cost no memory. On the
  first **write**, that triggers a copy-on-write fault (below) that allocates a real, zeroed
  frame. This is the case walked in Section 11.
- **File-backed demand paging.** The VMA maps a file and the faulting page isn't resident. The
  handler looks the page up in the file's **page cache** (Section 6); on a hit it just installs
  a PTE pointing at the cached folio, on a miss it allocates a folio and reads it in. This is
  how program text and `mmap`ed files load lazily — only the pages actually touched are ever
  read from disk.
- **Copy-on-write (COW).** After `fork`, parent and child share all their private pages
  **read-only** to avoid copying the whole address space (and to make `fork`+`exec` cheap).
  The shared frames are marked read-only in *both* page tables even though the VMAs are
  writable. When either process writes, the permission fault traps in; the handler sees a
  writable VMA over a read-only PTE on a shared page, **allocates a new frame, copies the
  contents, and installs a private writable PTE** for the faulting process — so each side gets
  its own copy only when it actually diverges. COW is also how the zero page is "upgraded" to a
  real page on first write.
- **Swap-in (major fault).** The PTE holds a **swap entry** (Section 7.7): the page was
  evicted to swap. The handler allocates a frame, reads the data back from the swap slot
  (checking the swap cache first), and reinstalls a present PTE. Because this involves disk
  I/O, it is counted as a **major fault**; the cases above that need no I/O are **minor
  faults**.
- **NUMA-hinting fault.** The PTE was deliberately made non-present to sample locality
  (Section 8.4); the handler records the access and possibly migrates the page, then restores
  the PTE.

In every case the handler ends by installing a valid PTE (allocating a frame and wiring up the
reverse mapping where needed) and the faulting instruction is **restarted**, now succeeding.
This lazy, fault-driven population is why a process can `mmap` gigabytes instantly and only pay
for the pages it touches — and it is the single mechanism through which the allocator, the page
cache, reclaim/swap, migration, and the page tables all meet.

---

<a name="11-putting-it-together"></a>
## 11. How the pieces fit: the life of an allocation

To see the subsystems cooperate, follow a process that touches a new heap page.

1. The process calls `malloc`, which (for a large request) `mmap`s anonymous memory. The kernel
   creates or extends a **`vm_area_struct`** in the process's `mm_struct` (indexed in the
   **maple tree**) but allocates **no physical memory** — this is lazy/demand allocation. The
   page tables for the region are empty.
2. The process writes to an address in that region. The MMU walks the page tables, finds the PTE
   **not present**, and raises a **page fault**. Control enters `do_page_fault` →
   `handle_mm_fault`.
3. The fault handler sees an anonymous region with no page, so it must allocate a frame. It calls
   into the allocator (`alloc_pages`/`folio_alloc` with `GFP_HIGHUSER_MOVABLE` — user data,
   movable, zeroed). For a write fault on fresh anon memory it may first hand out the shared
   **zero page** and only allocate on the *next* write, but assume a real allocation here.
4. The allocator picks the local **NUMA node** (per memory policy), walks that node's
   **zonelist**, and at the first zone above its **watermark** pulls an order-0 page — almost
   certainly from the **per-CPU page list**, lock-free. If every zone is below its watermark, it
   takes the **slow path**: wakes `kswapd`, tries **direct reclaim** (evicting cold pages via the
   LRU/MGLRU, possibly swapping or dropping clean page cache), maybe **compaction**, and as a
   last resort the **OOM killer**.
5. With a frame in hand, the handler zeroes it (security: no leaking another process's data),
   adds it to the appropriate **LRU list** (so reclaim can find it later), sets up its **reverse
   mapping** (anon_vma), and installs a **PTE** pointing at the frame with the right permissions
   (present, user, writable). It flushes any stale TLB entry for that address.
6. The faulting instruction is **restarted**; this time the MMU walk succeeds and the write
   completes. The page is now resident, tracked for reclaim, and reachable.

If later the system comes under memory pressure, `kswapd` may find this page cold (accessed bit
clear over time), unmap it via rmap with a TLB shootdown, write it to **swap**, free the frame
back to the buddy allocator, and leave a swap entry in the PTE — so a future access faults it
back in. If the process is on the wrong NUMA node, automatic balancing may **migrate** the page
closer. Every subsystem in this guide participated in the life of that one page.

---

<a name="12-glossary"></a>
## 12. Glossary

- **PFN** — Page Frame Number; a physical page's index (`physical address >> PAGE_SHIFT`).
- **`struct page` / `struct folio`** — descriptor for a physical frame / a group of frames
  managed as a unit (the folio is the modern unit of mm).
- **`pglist_data` (`pg_data_t`)** — a NUMA node's memory descriptor.
- **Zone** — a sub-range of a node's memory with shared addressing/mobility constraints
  (`ZONE_DMA`/`DMA32`/`NORMAL`/`MOVABLE`/`DEVICE`).
- **Buddy allocator** — the physical page allocator managing power-of-two free blocks per zone.
- **Migratetype** — mobility class of a pageblock (unmovable/movable/reclaimable/...), used for
  anti-fragmentation.
- **GFP flags** — per-allocation constraints (which zones, may it sleep/reclaim, etc.).
- **Watermark** — min/low/high free-page thresholds that drive reclaim.
- **PCP** — per-CPU page lists, a lock-free cache of free pages.
- **`memblock`** — the boot-time physical allocator used before the buddy allocator exists.
- **e820 / EFI memory map** — firmware's description of physical memory ranges.
- **SPARSEMEM / vmemmap** — the default memory model; a virtually-mapped `struct page` array
  tolerant of physical holes.
- **`address_space`** — the page cache's per-file structure; holds the XArray of cached folios
  and the filesystem's `a_ops`.
- **XArray** — the index from file offset to cached folio (successor to the radix tree).
- **Writeback / `balance_dirty_pages`** — flushing dirty cache to disk; throttling writers.
- **OPT / MIN / Belady** — the optimal (future-knowing, unimplementable) page-replacement
  policy; the ideal Linux's LRU approximates.
- **LRU / MGLRU** — the active/inactive (or multi-generational) page-replacement approximations.
- **rmap** — reverse mapping; finds every PTE mapping a given physical page.
- **Refault / workingset** — detecting wrongly-evicted pages via shadow entries to adapt reclaim.
- **Migration / compaction** — relocating pages; defragmenting by migrating movable pages into
  contiguous blocks.
- **PGD/P4D/PUD/PMD/PTE** — the (up to) five page-table levels on x86-64.
- **TLB / shootdown** — the translation cache; the IPI-based protocol to invalidate stale
  entries across CPUs.
- **THP / hugetlbfs** — transparent (automatic) and explicitly-reserved huge pages.
- **KPTI** — Kernel Page-Table Isolation (Meltdown mitigation; split user/kernel PGDs).
- **NUMA** — Non-Uniform Memory Access; memory access cost depends on which node holds the
  memory relative to the accessing CPU.
- **`mm_struct`** — a process's address-space descriptor (page-table root, VMAs, counters).
- **VMA (`vm_area_struct`)** — one contiguous virtual region with uniform backing/permissions.
- **Maple tree** — the range-indexed structure holding an `mm`'s VMAs (replaced the rbtree).
- **Compound page / tail page** — a higher-order page treated as a unit; its first frame is the
  *head*, the rest are *tail* pages. The folio type exists partly to keep head/tail explicit.
- **`lruvec`** — the per-(cgroup, node) container of LRU lists / MGLRU state used by reclaim.
- **`kswapd` / `kcompactd` / `khugepaged`** — per-node background threads for reclaim,
  compaction, and collapsing base pages into transparent huge pages, respectively.
- **Swap entry (`swp_entry_t`)** — a not-present PTE value encoding the swap area + slot that
  hold an evicted anonymous page.
- **COW (copy-on-write)** — sharing pages read-only until a write faults and triggers a private
  copy (used after `fork`, and to upgrade the zero page).
- **Demand paging** — populating page-table entries and frames lazily on fault, not up front.
- **Zero page** — a single shared read-only zeroed frame backing never-written anonymous pages.
- **memcg** — the cgroup v2 memory controller: per-cgroup accounting, limits, reclaim, and OOM.
- **Major / minor fault** — a fault that needs disk I/O (e.g. swap-in, file read) versus one
  that does not (demand-zero, COW, page-cache hit).

---

<a name="13-source-map"></a>
## 13. Source map and further reading

Key files in the v6.8 tree, by topic:

- **Nodes/zones/structures:** `include/linux/mmzone.h` (`pglist_data`, `struct zone`,
  `enum zone_type`, `enum migratetype`, watermarks, LRU/MGLRU structs),
  `include/linux/mm_types.h` (`struct page`, `struct folio`).
- **Boot/memory detection:** `mm/memblock.c`; `arch/x86/kernel/e820.c` and
  `arch/x86/kernel/setup.c`; `mm/sparse.c`, `mm/sparse-vmemmap.c`; `mm/mm_init.c`
  (`free_area_init`, watermark setup).
- **Page allocation:** `mm/page_alloc.c` (`__alloc_pages`, `get_page_from_freelist`,
  `__alloc_pages_slowpath`, the buddy split/merge, PCP, migratetype fallback);
  `include/linux/gfp.h`, `include/linux/gfp_types.h`.
- **Page cache:** `mm/filemap.c`, `mm/readahead.c`, `mm/page-writeback.c`;
  `include/linux/fs.h` (`address_space`, `address_space_operations`); `include/linux/xarray.h`.
- **Reclaim / OPT approximations:** `mm/vmscan.c` (classic LRU and MGLRU/`lru_gen`),
  `mm/workingset.c` (refault), `mm/rmap.c`, `mm/oom_kill.c`, `mm/swap_state.c`, `mm/swapfile.c`.
- **Migration/compaction/NUMA:** `mm/migrate.c`, `mm/compaction.c`, `mm/mempolicy.c`,
  `mm/memory-tiers.c`; NUMA-hinting fault handling in `mm/memory.c`.
- **Page tables:** `arch/x86/include/asm/pgtable.h` and `pgtable_types.h`;
  `include/asm-generic/pgtable-nop4d.h` / `-nopud.h` / `-nopmd.h` (folding); `mm/huge_memory.c`,
  `mm/hugetlb.c` (huge pages); TLB handling in `arch/x86/mm/tlb.c`.
- **Address space, VMAs, faults:** `include/linux/mm_types.h` (`mm_struct`, `vm_area_struct`),
  `include/linux/maple_tree.h` and `lib/maple_tree.c` (VMA index), `mm/mmap.c` (VMA
  management), `mm/memory.c` (`handle_mm_fault` and the fault cases), `arch/x86/mm/fault.c`.
- **Swap and memcg:** `mm/swapfile.c`, `mm/swap_state.c` (swap cache), `mm/page_io.c`;
  `mm/memcontrol.c` (cgroup v2 memory controller).

### Seeing it on a live system

The concepts above map to readable interfaces, which is the fastest way to make them concrete:

- `/proc/meminfo` — global totals (free, available, cached, dirty, writeback, slab, swap, ...).
- `/proc/zoneinfo` — per-zone free pages and watermarks (min/low/high).
- `/proc/buddyinfo` — free-block counts per order per zone (watch fragmentation).
- `/proc/pagetypeinfo` — free blocks broken down by **migratetype** (anti-fragmentation state).
- `/proc/vmstat` — counters for faults, reclaim, compaction, NUMA balancing, swap, etc.
- `/proc/<pid>/maps` and `/proc/<pid>/smaps` — a process's **VMAs** and their per-region memory.
- `numastat`, `/sys/devices/system/node/` — per-**NUMA-node** memory and hit/miss stats.
- `/sys/kernel/mm/transparent_hugepage/` and `/sys/kernel/mm/lru_gen/` — THP and MGLRU controls.
- `/sys/fs/cgroup/.../memory.*` — per-**cgroup** usage, limits, pressure, and events.

Background reading: Mel Gorman, *Understanding the Linux Virtual Memory Manager* (2.4/2.6 — the
conceptual scaffolding, though many specifics here have since changed); the kernel's own
documentation under `Documentation/mm/` and `Documentation/admin-guide/mm/` (including
`transhuge.rst`, `numa_memory_policy.rst`, and `multigen_lru.rst`); and LWN.net's long-running
coverage of mm changes (folios, the maple tree, MGLRU, memory tiering).

---

*Scope note: this guide describes the common x86-64 configuration. Other architectures
implement the same abstractions over different hardware (page sizes, table depth, DMA ranges,
TLB management), but the structures and policies above — `pglist_data`/zones, the buddy
allocator, the page cache, reclaim, migration, and the folded multi-level page-table walk — are
the shared core of the Linux memory manager as of v6.8.*
