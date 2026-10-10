---
id: RB-KPI-REFERENCE
title: KPI reference
tags: [kpi, definitions, normal-range, null-values, baseline, seasonality, units]
categories: []
---

# KPI reference

## Overview

This page defines the measurements in the KPI tables, their units, what normal looks like and what a missing value means. It exists to stop two mistakes: reading a normal busy hour as an incident, and reading a NULL as a zero. All series are sampled every 15 minutes. Timestamps are stored in UTC.

## Cell KPIs

One row per cell per 15-minute step in `cell_kpis`. A site has three cells, so site values are aggregates.

- `dl_volume_mb`, `ul_volume_mb`: data delivered in the step, in megabytes. Uplink is about 12 to 18 percent of downlink. Sum these over cells to get a site or region.
- `active_users`: number of connected users. Sum over cells.
- `rrc_success_pct`: share of connection setups that succeed. Normal 99.0 to 99.7.
- `drop_rate_pct`: share of sessions that end abnormally. Normal 0.4 to 0.8 percent.
- `latency_ms`: average round-trip time. Normal about 35 ms on 4G, about 18 ms on 5G, a few ms more at rural sites.
- `prb_util_pct`: share of radio resource blocks in use. Latency and drop rate begin to rise when it passes about 80 to 85 percent.
- `availability_pct`: share of the step that the cell was in service. Normal 100.

When aggregating quality KPIs, weight by volume and ignore NULLs. Take the mean for PRB and the minimum for availability when you want the worst case.

## What NULL means

When a cell is fully down (availability 0), it reports nothing for `rrc_success_pct`, `drop_rate_pct` and `latency_ms`, which are NULL. Volume, users and PRB are 0. Do not treat NULL as a perfect value. An average over a region that skips NULLs may look better during an outage, because the dead cells have dropped out. Always look at availability and the count of cells down first.

## Harmless micro-outages

Occasionally a single cell shows availability of 93.3, 86.7 or 73.3 for one step only: 1, 2 or 4 minutes of a 15-minute step. They recover by themselves and are not incidents. An outage is availability well below this for several consecutive steps, or at 0.

## Core KPIs

In `core_kpis`, long format with `node_id`, `metric`, `value`.

- DNS node: `query_success_pct` normally about 99.9, `resolution_ms` about 8 to 15.
- UPF nodes: `throughput_gbps` (sum of downlink volume of the regions served) and `session_count`. One UPF serves two regions.
- AMF node: `attach_success_pct`, normally about 99.5.

## Seasonality and baselines

Traffic follows a daily curve: lowest around 03:00 to 05:00, a morning rise, a midday plateau and the busiest period around 21:00 to 22:00 (local time). Weekends are lower in business areas and higher in suburban and rural areas. Never compare a value with the previous hour. Compare it with the same time of day on the same day type (weekday, Saturday or Sunday) over the previous days. A 50 percent drop from the evening peak to 03:00 is routine.

## Region view

The view `region_kpis_15m` aggregates cells by region and step: summed volume and users, volume-weighted latency, drop rate and RRC success, average PRB, `min_availability_pct`, and `cells_down` (cells with availability below 50). It is the cheapest way to see a regional pattern.

## Reading order for a suspicious series

Check availability and `cells_down` first. If they are normal, check volume and users against the baseline. Then check RRC success and drop rate, then latency together with PRB. A latency problem with low PRB points away from radio load.
