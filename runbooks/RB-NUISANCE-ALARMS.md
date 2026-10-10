---
id: RB-NUISANCE-ALARMS
title: Nuisance alarms and alarm storms with no impact
tags: [alarms, storm, noise, temp-high, vswr, flapping, no-impact]
categories: [no_impact]
---

# Nuisance alarms and alarm storms with no impact

## Overview

A telecom network raises alarms all day. Most are warnings or minor events that clear by themselves and never touch customers. A cabinet gets warm in the afternoon, a feeder reports a reflection, a door is opened during a visit. Now and then a single site raises dozens of such alarms within an hour, which looks alarming on a dashboard. An alarm count is not an impact. Before escalating, check what customers saw. If the KPIs are normal, the storm is a nuisance and the right answer is to say so.

## Signature in the data

- **Background noise.** On a typical day there are 10 to 30 alarms across the network: `TEMP_HIGH` (warning, mostly afternoons, flapping a few times), `VSWR_HIGH` (minor), minor `LINK_DEGRADED` (errored seconds, link within SLA), `CPU_HIGH` (warning, on routers), `DOOR_OPEN` (warning), `FAN_FAILURE` (minor, may last hours).
- **Alarm storm.** One site raises 20 to 50 minor or warning alarms in about an hour. The types are drawn from `TEMP_HIGH`, `VSWR_HIGH`, `DOOR_OPEN`, `FAN_FAILURE` and `RECTIFIER_FAULT`. Each alarm clears in a few minutes and a new one follows.
- **No customer impact.** For that site, `availability_pct` is 100, and volume, users, RRC success, drop rate and latency follow the normal curve for the hour.
- **No critical alarm.** No `SITE_DOWN`, `LINK_LOS`, `MAINS_FAILURE` or `BATTERY_LOW` in the same window.
- **No nearby change** that fits the timing, and no maintenance window.

## Differential diagnosis

### Versus a real outage with many alarms

A real failure produces few, severe alarms on several nodes: `critical` `SITE_DOWN` and `LINK_LOS`. A storm has many alarms of low severity on one node. Count by severity and by node, not by total.

### Versus a power problem in progress

A `RECTIFIER_FAULT` or a sustained `FAN_FAILURE` can precede a power or thermal shutdown. Look for `MAINS_FAILURE` or `BATTERY_LOW`. If neither exists and KPIs are normal, the site is fine for now. Mention the fault for follow-up.

### Versus a heat problem

`TEMP_HIGH` in the afternoon with normal availability is routine. Sustained `TEMP_HIGH` together with `FAN_FAILURE` that lasts hours deserves a maintenance ticket, not an incident.

### Versus an antenna problem that degrades service

`VSWR_HIGH` can mean a damaged feeder. If it is real, the sector's volume or RRC success would drift. When the site's KPIs are normal, it is a nuisance.

### Versus a decoy before a real incident

A minor alarm on a site 15 to 90 minutes before an outage on that site is a coincidence when a stronger cause, such as `LINK_LOS` or `MAINS_FAILURE`, explains the outage. Say that it cleared and had no KPI effect.

### Versus an alarm storm that is a symptom

If the site storm coincides with a hard outage upstream, the storm is a consequence. This is rare. With normal KPIs it is a nuisance.

## Verification steps

1. `get_alarms` for the site and the hour: count by type and severity, and read the clear times.
2. `query_kpis` for the site's cells over the same hour and the hours around it. Compare with the same hour on earlier days. Check availability first.
3. Look for any critical or major alarm on the site or its parents in the same window.
4. `get_maintenance` and `get_changes` for the site.
5. Check whether the site had similar storms before: repeated nuisance points to a hardware item to fix.

## Recommended actions

Do not dispatch. Log the storm for the site's maintenance planner, especially if the alarm types suggest a failing fan, rectifier or door sensor. Consider alarm thresholds or suppression for flapping alarms, so real signals stand out.

## Escalation

None as an incident. Create a low-priority maintenance ticket for repeated alarms. Escalate only if KPIs show impact or a critical alarm appears.
