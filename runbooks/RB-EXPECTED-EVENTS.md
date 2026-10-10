---
id: RB-EXPECTED-EVENTS
title: Expected traffic events, stadium and public holiday
tags: [event, stadium, venue, holiday, expected, traffic-surge, traffic-dip]
categories: [expected_event]
---

# Expected traffic events, stadium and public holiday

## Overview

Some large changes in traffic are not faults. A match or concert fills a venue with tens of thousands of phones. A national holiday empties the business districts and fills the residential areas. Both are recorded in the external events table (`event_type` is `stadium_event`, `public_holiday` or `festival`) with a region, a start and an end. Before treating a surge or a dip as an incident, check that table. If an event explains the pattern, the right report says so and closes the case.

## Stadium or venue event: signature

- **Where.** The few sites around the venue (`nodes.attrs.near_venue` is true), in one region. Sites a few kilometres away barely move.
- **When.** Usually the evening, starting before the event. Traffic ramps up over about an hour before kickoff and falls away more quickly afterwards. Total duration three to four hours.
- **Users and volume.** `active_users` and `dl_volume_mb` two to four times the normal level for the hour.
- **Radio load.** `prb_util_pct` high. Venue sites carry extra capacity, so they cope better than ordinary sites. Latency rises mildly, not by a factor of two to four.
- **Alarms.** `HIGH_PRB` warnings on one to three of the venue sites, 40 to 80 minutes after the start.
- **Availability.** 100 percent. No `SITE_DOWN`, no change.

## Public holiday: signature

- **Where.** The whole country, all regions together, for one calendar day.
- **Pattern.** Business-area (urban) cells lose about 30 percent of their daytime traffic. Residential cells gain about 10 percent. The net effect is a nationwide volume drop of 10 to 20 percent, strongest around midday.
- **Quality.** Latency, RRC success, drop rate and availability stay at normal levels. No alarms, no changes.
- **Core.** UPF `throughput_gbps` is lower for the day. DNS metrics are normal.

## Differential diagnosis

### Stadium event versus congestion

Both give high PRB and `HIGH_PRB`. The event has an `external_events` row covering the region and the evening, sits on venue sites, and has modest latency. Congestion has no event, can be anywhere, and shows latency two to four times above normal. If the event record exists but the saturated site is far from the venue, the event does not explain it.

### Holiday versus DNS degradation

Both lower nationwide volume. A holiday lasts all day, does not raise latency, has the business-versus-residential pattern and is on the calendar. DNS trouble lasts hours, raises latency, and shows bad DNS KPIs.

### Holiday versus a regional outage

A holiday affects all regions in the same proportion, and availability stays 100 percent. An outage affects specific sites and zeroes their availability.

### Event versus an event-time failure

A real fault can happen during an event. If sites near the venue are down, or latency is far worse than the event alone would cause, check alarms and availability. An event explains extra traffic. It does not explain missing traffic.

### Event versus date mismatch

An event row on a different day, region or far from the affected sites does not count. Match the time window and the sites.

## Verification steps

1. `get_external_events` for the region and the date, including nationwide events where the region is empty.
2. `get_topology` or node attributes: are the affected sites near the venue?
3. `query_kpis`: compare users, volume and PRB with the same hour on earlier days of the same type. Confirm the size of the change.
4. Check that availability, RRC success and drop rate are normal.
5. `get_alarms` for the venue sites: only `HIGH_PRB` warnings should appear.

## Recommended actions

Record the event as the explanation. Cite the event id and the matching KPI pattern in the report. No dispatch is needed. If capacity limits were reached, give the event to capacity planning for next time.

## Escalation

None for an explained event. Escalate if quality KPIs were also poor during it, or if the traffic pattern does not fit the event, since there may be a second problem hidden inside the expected one.
