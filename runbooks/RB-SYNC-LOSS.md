---
id: RB-SYNC-LOSS
title: Timing and synchronisation loss
tags: [sync, timing, gps, ptp, clock, holdover, phase]
categories: []
---

# Timing and synchronisation loss

## Overview

Radio equipment needs an accurate shared time and frequency reference. Sites get it from a GPS receiver or from the transport network through precision time protocol (PTP) or synchronous Ethernet. When the reference is lost, the equipment runs in holdover on its internal oscillator. For a while service continues. As the clock drifts, neighbouring cells interfere with each other, handovers fail, and in the worst case the radio shuts down to protect the network. The problem therefore arrives slowly and then suddenly.

## Signature in the data

- **Sync alarms.** A timing reference loss or holdover alarm on a site or a group of sites. This alarm set does not model them, so sync problems would appear only as KPI effects.
- **Slow drift.** During holdover, `drop_rate_pct` rises slowly and `rrc_success_pct` slips over hours, in a group of neighbouring cells.
- **Time-division effects.** Interference between neighbours, which shows as lower throughput and worse quality at cell edges.
- **Sudden end.** After holdover expires, cells may shut down and availability falls to 0.
- **Common source.** Sites sharing a GPS antenna problem, or a transport element distributing PTP, fail together.

## Differential diagnosis

### Versus a power or transport outage

Those start abruptly, with an alarm on the power or link. Sync loss starts quietly, with a slow quality drift before any outage.

### Versus RF interference from outside

External interference is not tied to a timing chain, and does not worsen steadily as holdover time passes.

### Versus a bad change

A change is a step at a known time. Sync loss is a drift that began with a reference failure.

### Versus congestion

Congestion has high PRB and users. Sync loss has normal load and degraded quality.

### Versus a microwave degradation

A degraded link lowers volume for all sites behind it and has a link alarm. Sync problems degrade quality in a geographic cluster of cells.

## Verification steps

1. Find a cluster of neighbouring cells with slowly worsening drop rate.
2. Check for GPS or timing alarms in the platform's native alarm list.
3. Check whether the affected sites share a timing source or a transport path carrying PTP.
4. Look at changes to the transport or timing equipment.
5. Look for availability falling after several hours, which would mean holdover expired.

## Recommended actions

Check the GPS antenna and receiver at the sites, and the sync distribution on the transport network. Switch to a backup reference if available. Plan for extended holdover oscillators at critical sites. Monitor the time until holdover expires, and act before it does.

## Escalation

Transport and timing engineers own the case. Severity grows with the number of cells in the cluster and shrinks with the time left before holdover runs out. Page the duty manager if a cluster is close to shutting down and no backup reference is available.
