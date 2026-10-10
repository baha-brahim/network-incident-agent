---
id: RB-ESCALATION
title: Severity and escalation matrix
tags: [severity, escalation, matrix, teams, sla, priority]
categories: [transport_failure, power_failure, bad_change, core_degradation, capacity, transport_degradation]
---

# Severity and escalation matrix

## Overview

Severity says how urgent an incident is. It depends on how many customers lose service and how badly, not on how many alarms fired. Escalation says who must act and when. Use this page to rate an incident and name the team that owns the fix.

## Severity levels

- **High.** A large share of customers lose service or suffer badly. Examples: a whole region or country affected, four or more sites down together, a change on an aggregation router, a core DNS fault. Respond at once.
- **Medium.** A few sites or one local area. Examples: one urban site down, one microwave link degraded, a site group hit by a bad change, congestion at one or two sites. Respond within the hour.
- **Low.** A rural site, a short event or a condition with no customer effect yet. Examples: a single rural site down, a repeated nuisance alarm. Handle in working hours.
- **No incident.** Expected outages (maintenance), expected traffic changes (events, holidays) and alarm storms with normal KPIs. Document and close.

## Factors that raise severity

More sites. More customers per site (urban over rural). Long duration. Nationwide scope. Loss of the only path to a site. A fault with no ETA. Missing alarm coverage.

## Factors that lower severity

The impact is partial and quality only. The affected sites are lightly loaded. A fix is already in progress. The event is fully explained by a record.

## Who owns what

- **Transport operations**: fiber cuts, link losses, microwave degradation.
- **Field operations and power**: mains failures, batteries, generators, site visits.
- **RAN operations and optimisation**: configuration regressions, congestion, interference, sleeping cells, upgrades.
- **Core and IP operations**: DNS, AMF, UPF and aggregation routers.
- **Change management**: any incident linked to a change, and any maintenance overrun.
- **Capacity planning**: repeated congestion.
- **Customer care**: needs the affected areas and expected restoration.

## Time-based escalation

- Page the owning team immediately for high severity, and within 15 minutes for medium.
- Escalate to the duty manager when a high-severity incident is not under control after 30 minutes, or any incident is not restored after four hours.
- Inform the director on call for outages that last more than a working day or affect the whole country.
- For a mains failure, the ticket window is the battery autonomy: act before `BATTERY_LOW`.

## What to include when escalating

The affected nodes and scope, the onset time (state the time zone), the hypothesised cause and your confidence, the alarms and ticket ids, what has been ruled out, and what you need from the team. Do not escalate a guess as a fact.

## De-escalation

Close when the KPIs return to their baseline for at least an hour and the alarms have cleared. If the cause was a change, wait for the rollback to settle. Record the final severity as the severity of the impact, not of the first alarm.
