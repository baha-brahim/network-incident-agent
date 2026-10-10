---
id: RB-BAD-CHANGE
title: Bad change and configuration regression
tags: [change, config, rollback, rrc, regression, parameter]
categories: [bad_change]
---

# Bad change and configuration regression

## Overview

A configuration push or a parameter template applied to an aggregation router, or to a group of sites, can make service worse without taking anything down. Nothing is unreachable and there are few alarms. Users simply cannot connect as often, calls drop more, and traffic dips. The regression starts when the change is executed and ends when it is rolled back, usually after hours of confusion. The signature is quality, not availability.

## Signature in the data

- **A change record.** In the change log, a `config_push` or `parameter_tuning` row on an aggregation router (which affects every site below it) or on each site of a group. Its status later reads `rolled_back`. The description can be bland, such as "scheduled parameter optimisation batch", so do not judge it by its wording.
- **A step at the change time.** In the 15-minute step of the change, `rrc_success_pct` falls by roughly three to seven points (for example from about 99.4 to 93 to 96), `drop_rate_pct` rises three to five times, and `dl_volume_mb` falls ten to thirty percent.
- **What stays normal.** `availability_pct` stays at 100 %. There is no `SITE_DOWN`. `latency_ms` moves little and `prb_util_pct` is normal or lower.
- **Alarms.** At most a minor `RRC_FAILURE_RATE_HIGH` on a few of the affected sites, 15 to 45 minutes after the change. Many sites affected with few alarms is typical.
- **The end.** A second change row of type `rollback`, with `rollback_of` pointing at the original, four to twenty-four hours later. KPIs return to baseline in the step of the rollback.

## Differential diagnosis

### Versus the many harmless changes

Several changes are logged every day across the network, such as antenna tilt, neighbour lists, software patches. Almost all have no effect. A change is a suspect only if its time matches the KPI onset within one step, and it sits on the common ancestor of the affected sites or on the sites themselves. A change on an unrelated node at roughly the same time is noise.

### Versus a decoy that precedes the real cause

A change executed 15 to 90 minutes before the onset, with KPIs still normal in between, did not cause it. Configuration changes act within a step or two. If a hard alarm such as `LINK_LOS` or `MAINS_FAILURE` sits at the onset, that alarm is the cause.

### Versus congestion

Congestion saturates the radio: `prb_util_pct` at 95 to 100 %, latency up two to four times, active users well above normal. A bad change leaves PRB normal or lower, latency flat, and drops RRC success. Users do not increase.

### Versus DNS degradation

DNS trouble is nationwide, raises latency and leaves RRC success alone. A bad change is confined to the changed subtree, lowers RRC success and leaves latency flat.

### Versus hardware failures

A fiber cut or power failure sets availability to 0. A bad change never does.

### Versus RF interference

Interference shows up per sector, follows a time-of-day pattern or builds gradually, and has no change record. A bad change is a clean step.

## Verification steps

1. `get_anomalies` for `rrc_success_pct` and `drop_rate_pct` on a set of sites; read the start time.
2. `get_topology`: find the common ancestor of the affected sites (aggregation router or link).
3. `get_changes` for that node and its sites in the 24 hours before the onset. Compare each executed time with the onset.
4. `query_kpis`: confirm availability is 100 % and the RRC step is aligned with the change. Use sites outside the changed subtree as a control group; they must be normal.
5. Find the rollback row and confirm KPIs recover at its time. Recovery after the rollback is the strongest evidence.

## Recommended actions

Roll back immediately if no rollback has happened. Check recovery within two steps. Freeze similar pushes until the template is reviewed. Ask the change owner to explain the approval, and require canary sites for future pushes to routers.

## Escalation

RAN operations and the change manager. Severity is high when the change was on an aggregation router (many sites), medium for a site group. If KPIs do not recover after rollback, the change was not the whole story, so reopen the investigation.
