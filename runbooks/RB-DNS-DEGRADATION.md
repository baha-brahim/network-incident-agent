---
id: RB-DNS-DEGRADATION
title: Core DNS degradation
tags: [dns, core, nationwide, latency, resolution, shared-dependency]
categories: [core_degradation]
---

# Core DNS degradation

## Overview

All regions share a single DNS node (`node_type` `core_dns`, id `CORE-DNS-01`). When it slows down or drops queries, every data session in the country is affected at once, while the radio network itself is healthy. Nothing is unreachable. Users report slow pages and failing apps, latency rises everywhere and traffic dips. Because the cause is a shared dependency, the pattern is nationwide and synchronous, which is the main clue. The raising of an alarm is not guaranteed.

## Signature in the data

- **Core KPIs on the DNS node.** `query_success_pct` falls from about 99.9 to between 85 and 93. `resolution_ms` rises five to twenty times from its normal 8 to 15 ms. These two series are the direct evidence and sit in `core_kpis`, not in cell KPIs.
- **Cell KPIs in every region, starting in the same step.** `latency_ms` up 40 to 120 percent, `dl_volume_mb` down 15 to 30 percent. The change ramps in over about five minutes.
- **What stays normal.** `rrc_success_pct`, `availability_pct` and `drop_rate_pct` are unaffected, because radio signalling does not need DNS. `prb_util_pct` goes down, not up, since traffic falls.
- **Alarm.** A `DNS_TIMEOUT_RATE` alarm, severity `major`, on the DNS node. It may lag the onset by ten minutes to an hour, or never be raised. A missing alarm does not weaken the case.
- **Duration.** One to three hours, then everything recovers together.
- **Other core metrics.** UPF `throughput_gbps` falls with the traffic. AMF `attach_success_pct` is unaffected.

## Differential diagnosis

### Versus a public holiday or other expected demand change

A holiday also lowers traffic in every region, but latency does not rise, the dip lasts all day, it follows a business-versus-residential pattern, and an `external_events` row exists. In a DNS fault the dip lasts hours, latency rises, and the DNS KPIs are off.

### Versus congestion

Congestion is local to a few sites and shows PRB at 95 to 100 percent. With DNS trouble latency is high while PRB is low. Latency that is not explained by load is the signature.

### Versus a bad change

A bad change affects one subtree, lowers RRC success and leaves latency flat. DNS trouble is nationwide, leaves RRC success alone and raises latency.

### Versus transport or power failures

Those set availability to 0 at specific sites. Here availability is 100 percent everywhere.

### Versus AMF or UPF trouble

An AMF problem lowers `attach_success_pct` and RRC or attach failures follow. A UPF problem shows as a drop in that UPF's `throughput_gbps` and `session_count` for its regions only. A single UPF covers some regions, not all.

### Versus a decoy on the DNS node

A `CPU_HIGH` warning or a minor change on the core node shortly before the onset is not enough. If the alarm cleared minutes after it was raised and DNS KPIs were normal afterwards, it did not cause the degradation. A change that overlaps the onset is a candidate worth checking.

## Verification steps

1. `get_anomalies`: look for latency and volume anomalies in all regions starting in the same step.
2. `query_kpis` on region level: latency up, volume down, RRC and availability flat.
3. `query_kpis` on core metrics of `CORE-DNS-01`: `query_success_pct` and `resolution_ms`. Do this even when there is no alarm.
4. `query_kpis` on PRB: confirm it fell.
5. `get_external_events`: rule out a holiday.
6. `get_changes` on core nodes in the six hours before the onset.
7. `get_alarms` on the DNS node, including any late `DNS_TIMEOUT_RATE`.

## Recommended actions

Ask core operations to check the DNS service: process health, resource usage, upstream resolvers and recent configuration. Fail over to a secondary resolver if one exists. Review query volume for abuse. Notify customer care that the problem is nationwide and short. Confirm recovery in `resolution_ms` and `query_success_pct` before closing.

## Escalation

Core and IP operations immediately, severity high, since the whole country is affected. Escalate to the duty manager if resolution times have not recovered after one hour. The single DNS instance is a known risk and belongs in the post-incident review.
