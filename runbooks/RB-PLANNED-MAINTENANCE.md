---
id: RB-PLANNED-MAINTENANCE
title: Planned maintenance verification
tags: [maintenance, window, expected-outage, site-down, link-los, calendar]
categories: [planned_maintenance]
---

# Planned maintenance verification

## Overview

Operations teams schedule work that needs an outage: battery replacement, fiber splicing, equipment swaps, router upgrades. During the approved window the affected nodes go down on purpose and raise the same alarms as a real failure. The investigator's job is to check the calendar before declaring an incident. An outage that sits inside a window is expected. It is not an incident, and an alarm storm of `SITE_DOWN` or `LINK_LOS` inside a window is not a reason to escalate.

## Signature in the data

- **A row in the maintenance table.** It has `node_id`, `start_at`, `end_at`, a description, `expected_impact`, and a status of `planned` or `completed`.
- **Outage inside the window.** The affected sites fall a few minutes after the start and recover a few minutes before the end, so the outage is slightly shorter than the window.
- **Alarms look like a failure.** `SITE_DOWN` critical on the sites. If the work is on a link, `LINK_LOS` critical on the link node too.
- **KPIs.** Availability 0, volume and users 0, and quality KPIs NULL for the affected cells, exactly as in a real outage.
- **The description varies.** "Planned fibre splice work", "battery replacement and cabinet inspection", or a vague "routine transport network works, possible short service interruptions". The vague form is still a valid window if the scope and time fit.

## Differential diagnosis

### Four tests for an expected outage

All four must pass.

1. **Scope.** The maintenance node is the failed node or one of its ancestors. A window on a link covers its downstream sites. A window on one site does not cover its neighbour.
2. **Time.** The outage lies inside the window, with a small tolerance at both ends. It must not start before the window or run after it.
3. **Nature.** The work could cause this outage. Splicing or battery replacement can. A window whose expected impact says "None expected" does not explain a total outage.
4. **Status.** The window is `planned` or `completed`, not a future entry that has not started.

### Versus a fiber cut that happens near a window

A cut on a different link, or one that begins before the window starts, is a real incident even if a window exists elsewhere. A window on a link does not cover the same hour on another link.

### Versus an overrun

If the outage continues after the window ends, the window explains only the part inside it. Report the overrun separately. The work did not finish on time, which is itself something to escalate.

### Versus a power failure at a site with a maintenance window

A window for an inspection with no expected impact does not cover a `MAINS_FAILURE`. Check whether the sequence of alarms matches the work.

### Versus alarm count

A window produces a large number of critical alarms. Count and severity do not distinguish it from a failure. The calendar does.

## Verification steps

1. `get_maintenance` for the affected node, its parents (link, aggregation router) and the failed sites, around the outage.
2. Compare each window's `start_at` and `end_at` with the first and last unavailable steps in `query_kpis`.
3. Compare `description` and `expected_impact` with what happened.
4. `get_alarms` to see whether anything appears outside the window, such as an alarm before the start.
5. Confirm all affected sites are covered. A site that failed but is outside the window's scope still needs an explanation.

## Recommended actions

If all four tests pass, record the outage as expected. Name the maintenance record in the report as the reason, and state that the hypothesis of a fault was considered and dismissed. Check that service is back at the end of the window. No dispatch is needed.

## Escalation

None if the window explains the outage. Escalate to the change owner if the work overruns, or to the incident process if any of the four tests fail.
