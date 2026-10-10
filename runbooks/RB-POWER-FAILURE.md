---
id: RB-POWER-FAILURE
title: Site power failure and battery autonomy
tags: [power, mains, battery, site-down, autonomy, outage]
categories: [power_failure]
---

# Site power failure and battery autonomy

## Overview

A cell site that loses AC mains keeps running on its batteries. Autonomy is limited, roughly one to four hours depending on load, battery age and temperature. Service continues normally until the batteries are empty, then the site drops off the network. Cause and symptom are therefore hours apart. The root cause time is the `MAINS_FAILURE` alarm, not the moment the traffic disappears. Investigators who start from the traffic drop often look at the wrong hour.

## Signature in the data

- **t0, mains lost.** `MAINS_FAILURE`, severity `major`, on the site ("running on battery"). KPIs are completely normal after this alarm: availability 100 %, volume and users on their usual curve.
- **About 15 minutes before the end of the battery.** `BATTERY_LOW`, severity `major`.
- **Battery empty.** `SITE_DOWN`, severity `critical`, within a minute of the KPI drop. From this step on, the site's cells show `availability_pct` 0, volume, users and PRB at 0, and `rrc_success_pct`, `drop_rate_pct` and `latency_ms` NULL.
- **Recovery.** Mains returns, and the alarms clear about two minutes after the site is back. The total outage after the batteries die is one to five hours.
- **Scope.** One site. Its neighbours, and the other sites on the same link, are unaffected.

## Differential diagnosis

### Versus a fiber cut

A fiber cut takes down every site under a link in the same step and raises `LINK_LOS`. A power failure is one site, preceded by mains and battery alarms, with no link alarm. If the site is alone and its siblings are fine, do not blame the link.

### Versus planned maintenance

Battery replacement or generator tests appear in the maintenance calendar, often with expected impact "None expected". Look for a window on that site that covers the outage. A `MAINS_FAILURE` alarm is never part of a planned window. If the window says no impact was expected and the site is dead, the window does not explain it.

### Versus a change or alarm close to the site-down time

A change, a firmware patch or a `TEMP_HIGH` or `VSWR_HIGH` alarm shortly before `SITE_DOWN` is a coincidence when `MAINS_FAILURE` came hours earlier. The site was healthy on batteries until the batteries were empty, and a change cannot cause that timing. The same goes for a harmless alarm just before the mains alarm: it cleared and the KPIs did not move.

### Versus a rectifier or equipment fault

A `RECTIFIER_FAULT` alone, with no `MAINS_FAILURE` and normal KPIs, is a minor hardware issue. It can shorten autonomy if the batteries stopped charging, so note it, but it is not an outage. A `SITE_DOWN` with no mains alarm and no battery alarm is not proven to be power. Check transport and equipment.

### Versus a grid event

If many sites in one area raise `MAINS_FAILURE` at about the same time, the cause is still mains, but the scope is the utility grid, and the recovery depends on the utility.

## Verification steps

1. `get_alarms` for the site, from twelve hours before the `SITE_DOWN`: find `MAINS_FAILURE` and `BATTERY_LOW`.
2. `query_kpis` at site level: confirm availability stays at 100 % until the `SITE_DOWN` step. The KPI onset must match the battery end, not the mains alarm.
3. Compute autonomy as the `SITE_DOWN` time minus the `MAINS_FAILURE` time. Under one hour suggests weak batteries; over four hours is unusual.
4. `get_topology`: confirm sibling sites on the same link are fine.
5. `get_maintenance` for the site around both times.
6. `get_changes` for the site: list anything between `MAINS_FAILURE` and `SITE_DOWN`, and say why it is not the cause.

## Recommended actions

While the site is still on battery, send the power team with a generator. The window is the autonomy time, and it is the only point at which the outage is preventable. After the batteries die, restoration depends on mains or a generator. Plan a battery capacity test once power is back. Rural sites are slower to reach, so expect longer outages.

## Escalation

Field operations and power at the first `MAINS_FAILURE` that lasts more than 30 minutes. Escalate when `BATTERY_LOW` appears with no technician on the way. Severity is medium for urban and suburban sites and low for rural ones. Raise it if many sites show mains failures together.
