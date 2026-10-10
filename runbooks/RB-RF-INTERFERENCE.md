---
id: RB-RF-INTERFERENCE
title: RF interference
tags: [interference, uplink, noise-floor, pim, radio, external-source]
categories: []
---

# RF interference

## Overview

Radio interference raises the noise floor of one or more cells. The cell hears worse, so users need more power and more retransmissions, sessions fail to set up and calls drop. The source may be external, such as an illegal repeater, a faulty electrical installation or a jammer, or internal, such as passive intermodulation from a corroded connector, or a neighbouring cell with a wrong power setting. The network stays up. The effect is a long, annoying quality loss that often follows a daily or weekly rhythm.

## Signature in the data

- **Quality worse, availability fine.** `rrc_success_pct` falls, `drop_rate_pct` rises, and `latency_ms` rises moderately. `availability_pct` stays 100.
- **Uplink first.** Uplink problems dominate. Uplink volume can fall more than downlink.
- **Per sector, not per router.** One or two sectors of a site, or a handful of sites in one area, are affected. Sectors facing a source are worse than those facing away.
- **Rhythm.** The degradation tends to return at the same hours, for example when an industrial machine or a broadcast transmitter operates. It may build gradually, not as a step.
- **Low PRB.** `prb_util_pct` is normal or low, so this is not load.
- **Alarms.** Often none. A `VSWR_HIGH` alarm on the same sector can point to a feeder or connector problem, which can generate passive intermodulation.
- **No change** that matches the start.

## Differential diagnosis

### Versus a bad change

A configuration regression is a clean step at the time of a change record, over a whole router or site group. Interference has no change record, hits individual sectors, and follows time of day.

### Versus congestion

Congestion shows PRB at 95 to 100 percent and more users. Interference has normal PRB and normal users.

### Versus backhaul degradation

A degraded link lowers volume and raises latency for every site behind it at once, with a link alarm. Interference is local to sectors.

### Versus DNS degradation

DNS trouble is nationwide and leaves RRC success unaffected. Interference lowers RRC success locally.

### Versus a sleeping cell

A sleeping cell has no users. An interfered cell has users who fail to connect or drop.

### Versus a harmless VSWR alarm

A `VSWR_HIGH` minor alarm appears frequently without effect. Only if the sector's quality KPIs move with it is the antenna system part of the cause.

## Verification steps

1. Find the affected sectors and compare quality KPIs by hour of day over several days.
2. Check whether degradation correlates with a clock pattern.
3. Compare sectors of the same site; look at azimuth.
4. Check the alarms for `VSWR_HIGH` and the changes for any antenna work.
5. Ask for spectrum analyser readings or uplink noise measurements from the radio.

## Recommended actions

Send the field team with a spectrum analyser to locate the source. Inspect feeders, jumpers and connectors for corrosion or damage. If the source is external, report it to the spectrum regulator. As a temporary measure, adjust the uplink power control or the antenna tilt.

## Escalation

RAN optimisation owns the case. Severity is low or medium, depending on how many sectors and how many customers are affected. Escalate to the spectrum regulator when the source is external, and to the field team when a site inspection is needed.
