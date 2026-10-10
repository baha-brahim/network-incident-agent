---
id: RB-CONGESTION
title: Radio capacity congestion
tags: [congestion, prb, capacity, latency, busy-hour, high-prb]
categories: [capacity]
---

# Radio capacity congestion

## Overview

Congestion means demand exceeds the radio capacity of one or a few sites. The radio resource blocks are exhausted, queues build up, and every user on those cells gets worse service. Nothing is broken: the site is up, alarms are mild, and the configuration has not changed. This differs from a normal busy hour in degree and in time of day. A true congestion incident is a surge that nobody announced.

## Signature in the data

- **Saturation.** `prb_util_pct` of the site's cells sits at 95 to 100 percent for one to four hours. In a normal busy hour it stays well below 80.
- **Users.** `active_users` is about 1.5 to 2.5 times what the same cells have at the same hour on previous days.
- **Volume.** `dl_volume_mb` reaches the capacity ceiling and stops growing. Volume per user falls.
- **Quality.** `latency_ms` rises two to four times (from about 35 ms to well over 100 ms on 4G), `drop_rate_pct` climbs, `rrc_success_pct` slips.
- **Availability.** 100 percent. No `SITE_DOWN`.
- **Alarm.** `HIGH_PRB`, severity `warning` ("PRB utilisation above 90%"), raised 10 to 25 minutes after the start and cleared shortly after the end.
- **Timing and scope.** Usually afternoon to evening. One or two sites in the same region, urban or suburban.
- **Context.** No row in `external_events` explains it and no change precedes it.

## Differential diagnosis

### Versus a stadium event or other expected demand

An event also brings users, high PRB and `HIGH_PRB` alarms. Look in `external_events` for a record covering the time and the region, and check whether the site is near the venue (`nodes.attrs.near_venue`). Venue sites have extra capacity, so latency rises mildly. If a matching event exists, the surge is expected and not an incident. If no event exists, or the site is far from the venue, it is congestion.

### Versus a normal busy hour

Compare with the same time of day on the same day type over the previous days. If PRB peaks at the same level every evening, it is a capacity planning matter, not an incident. An incident means the level is clearly above its own history.

### Versus a decoy parameter change

A scheduler or parameter tuning on the site shortly before the surge is harmless. A parameter change does not make users appear. If active users jumped, demand is the driver.

### Versus a bad change

A bad change lowers RRC success with PRB normal or lower and no user increase. Congestion raises PRB and users.

### Versus DNS degradation

DNS trouble is nationwide with low PRB and high latency. Congestion is local with high PRB.

### Versus microwave degradation

A degraded backhaul reduces volume while PRB stays normal or falls, and users are normal. Congestion has high PRB and high users.

### Versus a neighbouring outage

If a neighbouring site is down, its users may move to this one. Check whether a nearby site lost traffic at the same time.

## Verification steps

1. `query_kpis` for the site's cells: PRB, active users, latency, volume against the same hour in earlier days.
2. `get_alarms`: `HIGH_PRB` on the site and its start time.
3. `get_external_events` for the region at that time.
4. `get_topology`: is the site flagged as near a venue, and what are its neighbours?
5. `get_changes` for the site in the preceding 24 hours.
6. Check neighbours' traffic for a shift.

## Recommended actions

Short term: rebalance load to neighbouring cells, adjust cell reselection and carrier aggregation, and apply admission control to protect existing sessions. Medium term: add capacity or a carrier at the site if the site repeats this. Find out why demand jumped, for example an unannounced gathering. Record the site for capacity planning.

## Escalation

RAN optimisation during the event; capacity planning afterwards. Severity is medium. If the same site saturates on several evenings, open a capacity case rather than an incident.
