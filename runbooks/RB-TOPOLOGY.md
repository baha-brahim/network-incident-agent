---
id: RB-TOPOLOGY
title: Topology and blast radius guide
tags: [topology, blast-radius, dependency, parent, node-ids, hierarchy]
categories: [transport_failure, power_failure, bad_change, core_degradation, transport_degradation]
---

# Topology and blast radius guide

## Overview

The network is a dependency tree. A failure high in the tree takes everything below it. To find the root cause of a multi-site problem, find the lowest node that all affected sites share. If the affected set is exactly the children of one node, that node is the first suspect. If the set is only some of the children, the cause is probably lower down, at the sites.

## Node types and ID formats

The `nodes` table holds every element, with `node_type`, `region_id`, `parent_id` and an `attrs` JSON column.

- **Cell**: `C-XXX-NNN-S`, where XXX is the region code, NNN the site number and S the sector (1 to 3). Three cells per site. Technology 4G or 5G.
- **Site**: `S-XXX-NNN`. The parent is a transport link. `attrs` has area type (urban, suburban, rural), coordinates and a `near_venue` flag.
- **Transport link**: `LNK-XXX-NN-A` (the letter A, B or C numbers the link under its router). The parent is an aggregation router. `attrs.medium` is `fiber` or `microwave`. Each link serves three to five sites.
- **Aggregation router**: `AGG-XXX-NN`. Two per region. The parent is a UPF.
- **Core**: `CORE-UPF-NN` (user plane, each serving two regions), `CORE-DNS-01` and `CORE-AMF-01` (shared by every region, one instance each).

## The dependency chain

cell, then site, then transport link, then aggregation router, then UPF. DNS and AMF are not in the parent chain, but every cell depends on them, which is why a DNS or AMF fault shows up everywhere at once.

## Blast radius rules

- **One site down, siblings fine.** The cause is at the site (power, equipment, local alarm), or a planned window on the site.
- **All children of one link down, nothing else.** The link, or work on the link.
- **Some, but not all, children of a link degraded.** A site-level or sector-level problem.
- **All links under one router.** The router, or a change on it.
- **Both routers of a region, or all regions.** Suspect a UPF, a shared service or a nationwide cause.
- **All regions together with radio healthy.** DNS or a nationwide event such as a holiday.

## Finding downstream sites

A recursive query on `nodes.parent_id` lists everything below a node:

```sql
WITH RECURSIVE below AS (
  SELECT node_id, node_type FROM nodes WHERE parent_id = 'LNK-XXX-NN-A'
  UNION ALL
  SELECT n.node_id, n.node_type FROM nodes n JOIN below b ON n.parent_id = b.node_id
)
SELECT node_id FROM below WHERE node_type = 'site';
```

To find siblings, select the sites that share the same `parent_id`.

## Matching alarms to the tree

An alarm on a parent explains children's symptoms when the children's alarms and KPIs appear after it, within a few minutes. `LINK_LOS` on a link followed by `SITE_DOWN` on its children is one incident, not many. A `SITE_DOWN` on a site whose parent link has no alarm needs its own cause. Do not blame a link for a site that is not below it.

## Cross-checks

- Compare the affected sites with the unaffected ones that share the same parent. The unaffected siblings are the control group.
- Confirm that every site you attribute to a link is in the link's child list, and none outside it.
- Do not count the region as the unit. The same region can have several independent incidents at the same time on different branches. Keep them separate.
- Venue sites (the `near_venue` flag) can show traffic surges that are unrelated to faults.

## Shared dependencies

A core node serving every region (DNS, AMF) cannot be located by comparing regions, since all are hit. Use core KPIs for these nodes directly, and compare cell latency or attach metrics before and after.
