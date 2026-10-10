---
id: RB-SLEEPING-CELL
title: Sleeping cell
tags: [sleeping-cell, silent-failure, radio, zero-traffic, cell-outage, reset]
categories: []
---

# Sleeping cell

## Overview

A sleeping cell is a cell that looks healthy to the management system but no longer serves users. It broadcasts, or is marked in service, yet attaches nobody. There is typically no alarm because the software believes the cell is fine. The usual causes are a stuck baseband process, a corrupted radio configuration after a restart, or a crashed scheduler. The fault is invisible to alarm-based monitoring and is found by watching traffic.

## Signature in the data

- **One cell, not the site.** `active_users`, `dl_volume_mb` and `ul_volume_mb` of a single cell fall to zero or close to it, while its sister sectors at the same site carry normal traffic.
- **Availability looks normal.** `availability_pct` stays at 100, because the cell is reported as in service. This is what separates it from a down cell.
- **Neighbour effects.** Neighbouring cells may carry more load as users move to them, and may show a small rise in PRB and latency.
- **No alarm** specific to the cell. Sometimes an unrelated minor alarm appears around the same time.
- **Persistence.** The condition lasts until someone resets the cell. It does not recover on its own, and it does not follow the daily curve.
- **Quality KPIs.** `rrc_success_pct`, `drop_rate_pct` and `latency_ms` of the sleeping cell are often missing or meaningless, since there are no users.

## Differential diagnosis

### Versus an ordinary cell outage

A down cell shows availability 0 and NULL quality KPIs. A sleeping cell shows availability 100 with no traffic.

### Versus a site-wide problem

If all three cells of the site lose traffic, the cause is at site level or above: backhaul or power. One cell only points to a cell fault.

### Versus a night-time lull

Compare with the same hour on previous days. A low-traffic rural cell at 04:00 is normal. A busy-hour cell with no users is not.

### Versus a backhaul or configuration issue

Backhaul loss takes all cells and lowers availability. A bad configuration change usually hits a group of sites and drops RRC success, not traffic to zero.

### Versus a neighbour congestion event

If neighbouring cells are saturated because a sleeping cell dropped its users, the congestion is a consequence. Find the cell that lost its traffic first.

## Verification steps

1. Compare the three cells of the suspect site over the last day: one flat, two normal.
2. Check availability and active users of the suspect cell against its own history.
3. Check for any alarm, change or restart on the site in the hours before the traffic stopped.
4. Check the neighbours for load shift.

## Recommended actions

Request a remote reset of the cell. If it recovers, log the event and watch it for a day. If it repeats, schedule a software check or a baseband replacement. Add a monitoring rule that flags cells with zero users in the busy hour while availability is 100 percent.

## Escalation

RAN operations. Severity low or medium, depending on the cell's usual load. Escalate to the vendor if resets do not hold.
