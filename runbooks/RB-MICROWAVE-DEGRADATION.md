---
id: RB-MICROWAVE-DEGRADATION
title: Microwave link degradation
tags: [microwave, backhaul, rain-fade, link-degraded, modulation, throughput]
categories: [transport_degradation]
---

# Microwave link degradation

## Overview

Some transport links are microwave radio, not fiber (`nodes.attrs.medium` is `microwave`, with `band_ghz` and `length_km`). Heavy rain absorbs the signal (rain fade), and antenna misalignment or equipment faults do similar damage. The radio responds by dropping to a lower modulation, which cuts capacity. The link stays up, so the sites behind it stay up, but they cannot push as much traffic. The result is a soft degradation: slower service and falling volume with no outage.

## Signature in the data

- **Alarm.** `LINK_DEGRADED`, severity `major`, on the microwave link a few minutes after the start ("running at reduced modulation, RSL below threshold"). It clears a few minutes after recovery.
- **Downstream sites** (three to five behind that link): `dl_volume_mb` down 20 to 50 percent, `latency_ms` up 30 to 100 percent.
- **Availability.** Roughly 100 percent. Occasionally a few steps dip to 95 to 99 percent. There is no `SITE_DOWN`.
- **Other quality KPIs.** `prb_util_pct` stays normal or falls. `active_users` is about normal.
- **Shape.** Gradual: ramps in and out over about 15 minutes and fluctuates while the fade changes. Lasts one to six hours.
- **Scope.** Exactly the children of the one link. Sites on other links are fine.

## Differential diagnosis

### Versus the harmless background LINK_DEGRADED

The network raises minor `LINK_DEGRADED` alarms on links all the time ("minor errored seconds, link still within SLA"). They last 5 to 30 minutes, flap, and the sites' KPIs do not move. A major alarm on a microwave link with volume and latency moving is a different thing. Judge by severity, duration and KPI effect, not by the alarm name alone.

### Versus a fiber cut

A cut gives availability 0, `LINK_LOS` critical and `SITE_DOWN` on every site. Degradation keeps availability high and has no `SITE_DOWN`. If the link is fiber, rain fade cannot be the explanation.

### Versus a fiber link starting to fail

On a fiber link, a minor `LINK_DEGRADED` with falling optical power can precede a cut by up to an hour. If volume then goes to zero and `LINK_LOS` appears, the cut is the incident and the degraded alarm is its precursor.

### Versus congestion

Congestion has `prb_util_pct` at 95 to 100 and a user surge, at one or two sites. Backhaul limitation lowers volume while PRB stays low and users are normal, and it hits every site behind the link together.

### Versus a bad change

A bad change lowers RRC success and drop performance, not latency and volume with an alarm on the link. Check `get_changes` for the link and its sites.

### Versus a single-site antenna problem

A `VSWR_HIGH` alarm affects one site's antenna, not all sites behind a link. Several sites degrading together point to the shared link.

## Verification steps

1. `get_alarms`: find a major `LINK_DEGRADED` on a link, with the time.
2. `get_topology`: confirm the link is microwave and list its downstream sites.
3. `query_kpis` on those sites: volume down, latency up, availability near 100 percent, PRB not high.
4. Compare with sites on other links under the same aggregation router; they should be normal.
5. Check weather information if the site has it, for rain at the time.
6. `get_changes` and `get_maintenance` on the link, to rule them out.

## Recommended actions

Ask transport operations to read the radio's receive signal level and modulation state. If it correlates with rain, no repair is needed beyond watching it. If the level stays low in dry weather, send a team to check alignment, the antenna and the radio unit. Consider traffic prioritisation while capacity is reduced. If the link repeats this often, plan a fade margin review, a longer-term fiber migration or a protection path.

## Escalation

Transport operations. Severity is medium. Escalate to planning when the same link degrades repeatedly, since the link is under-dimensioned for the weather.
