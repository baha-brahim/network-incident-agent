---
id: RB-FIBER-CUT
title: Fiber cut on a transport link
tags: [transport, fiber, link, los, site-down, outage, backhaul]
categories: [transport_failure]
---

# Fiber cut on a transport link

## Overview

A transport link (node type `transport_link`, id like `LNK-XXX-NN-A`) carries all the traffic of the sites behind it, usually three to five. When the fiber is cut, or the optic or port on the link fails, every one of those sites loses its backhaul at the same moment. The sites themselves are healthy. The root cause is the link, not the sites, so the report must name the link and treat the site alarms as consequences. Repairs take from about two hours to most of a working day.

## Signature in the data

- **Alarms.** A `LINK_LOS` alarm, severity `critical`, on the link node at time t0 ("no light received on uplink port"). One to two minutes later a `SITE_DOWN` alarm, severity `critical`, on each downstream site ("OAM heartbeat lost"). All of them clear within a few minutes of the repair, the link alarm first.
- **KPIs, every cell of every downstream site, same 15-minute step.** `availability_pct` goes to 0. `dl_volume_mb`, `ul_volume_mb`, `active_users` and `prb_util_pct` go to 0. `rrc_success_pct`, `drop_rate_pct` and `latency_ms` become NULL, not zero, because a dead cell reports nothing.
- **Sites on sibling links under the same aggregation router are untouched.** The affected set is exactly the children of one link.
- **Optional precursor.** Twenty to sixty minutes before the cut a minor `LINK_DEGRADED` alarm may appear on the same link with falling optical receive power. It marks a failing fiber or optic and is part of the same incident.
- **Detector view.** Several anomalies in one region that start in the same step, each with availability and volume drops.

## Differential diagnosis

### Versus planned maintenance

The alarms are identical: `LINK_LOS` plus `SITE_DOWN`. Only the maintenance calendar separates them. If a window covers the link (or the aggregation router above it) and the outage sits inside the window, it is expected and not an incident. If the outage starts before the window, runs past its end, or involves a different link, treat it as a real cut.

### Versus a site power failure

A power failure hits one site, never its siblings. It starts with `MAINS_FAILURE` hours before the site goes down and has no `LINK_LOS`. Several sites losing service in the same minute under one link is not a coincidence of independent power failures.

### Versus microwave degradation

A degraded microwave link keeps its sites up. Availability stays near 100 %, volume falls by a fraction, and the alarm is a major `LINK_DEGRADED`. `LINK_LOS` with availability at zero is a hard failure. Check `nodes.attrs.medium`: a microwave link can also fail hard, and the data then looks like a fiber cut, although the repair is different.

### Versus a decoy change or alarm on one site

A harmless change or a `TEMP_HIGH` or `VSWR_HIGH` alarm on one downstream site, 15 to 90 minutes before the outage, is a coincidence. A single-site event cannot take down its siblings, and the `LINK_LOS` already explains the timing. Say in the report that you checked it and set it aside.

### Versus a failed aggregation router

If every link under one aggregation router is down, the shared parent is the cheaper explanation. Look for alarms on the `AGG-` node. A `CPU_HIGH` warning alone does not make an outage.

### Versus core problems

DNS or AMF trouble leaves availability at 100 % and affects all regions, not one link.

## Verification steps

1. `get_alarms` for the two hours around the first drop: find `LINK_LOS` on a link and list the `SITE_DOWN` sites.
2. `get_topology` for that link: confirm the `SITE_DOWN` set equals the children of the link, no more and no fewer.
3. `query_kpis` on availability for those sites: confirm they fall in the same step, and that a sibling link's sites do not.
4. `get_maintenance` for the link, its sites and the aggregation router, around the onset.
5. `get_changes` for the link and its sites in the three hours before. Check that KPIs were still normal between any change and the alarm.
6. Read `cleared_at` on the link alarm for the restoration time.

## Recommended actions

Dispatch the transport field team with the link id, the list of downstream sites and the time of the alarm. Ask for optical power readings at both ends. If the network has a protection path, check whether it should have taken over. Tell customer care which areas are affected. After the repair, confirm availability returns to 100 % and volume to baseline within one or two steps, and watch for flapping.

## Escalation

Transport operations at once. Rate severity high when four or more sites are down, medium otherwise. Escalate to the duty manager if the link is not restored after four hours, or if more than one link under the same router is involved.
