---
id: RB-TRIAGE
title: Incident triage in the first 15 minutes
tags: [triage, procedure, first-response, checklist, investigation-order]
categories: [transport_failure, power_failure, bad_change, core_degradation, capacity, transport_degradation, planned_maintenance, expected_event, no_impact]
---

# Incident triage in the first 15 minutes

## Overview

The first quarter of an hour decides whether the investigation goes straight to the cause or wanders. The order below is built to rule out harmless explanations first, then separate hard failures from soft degradations, and only then name a cause. Most wrong conclusions come from taking the first suspicious thing, such as a recent change or a noisy alarm, as the cause without checking the timing. Write down every hypothesis you drop and why.

## Step 1: define the symptom

State the question in measurable terms before querying anything. Which KPI moved (availability, volume, latency, RRC success, drop rate, PRB), in which direction, and where (one cell, one site, several sites, a region, the whole country). Which time zone is the user speaking in? Timestamps in the database are UTC and field staff speak local time, so convert before searching.

## Step 2: find the onset

Use the anomaly list and the KPI series to find the first anomalous step, to 15-minute resolution. The onset is the anchor for everything else. Events that happened after it cannot be causes. Events long before it need a mechanism that explains the delay: a mains failure and battery autonomy is one, a coincidental change is not.

## Step 3: classify by the shape of the effect

- **Availability falls to 0 and quality KPIs go NULL.** A hard outage: transport, power or maintenance.
- **Availability near 100 but volume or quality moved.** A soft degradation: bad change, congestion, microwave degradation, DNS.
- **Everything moved, in all regions, together.** A shared dependency: DNS first, or an expected nationwide event.
- **Nothing moved but alarms are noisy.** A nuisance.

## Step 4: check the calendar before anything else

Query the maintenance table and the external events table for the affected nodes, regions and time. If a window or an event explains the pattern, the incident is dismissed with a citation. Do this before dispatching anyone.

## Step 5: read the alarms

Pull alarms on the affected nodes and their parents around the onset. Sort by severity. A critical alarm on a shared parent (link, router) is a stronger lead than a dozen warnings on one site. Note when each alarm was raised relative to the KPI onset.

## Step 6: map the blast radius

Use the topology to find the lowest common ancestor of the affected sites. If they share a link, test the link. If they share a router, test the router. If they share nothing, test shared dependencies (DNS, AMF) or a nationwide cause. See the topology guide.

## Step 7: check changes

Look for changes on the common ancestor and the affected nodes shortly before the onset, and apply the change correlation policy. A change is a suspect only if its timing fits within one or two steps and the KPI shape fits a configuration problem.

## Step 8: state competing hypotheses

List the two or three candidates, the evidence for and against each, and what check would separate them. Run those checks. Use the runbook's differential diagnosis for each candidate. Rank the survivors.

## Step 9: write the report

Follow the report guide. Name the root cause, the time of the root cause, what was ruled out, the confidence, and cite each claim.

## Time budget

Steps 1 to 3 take a few minutes. Steps 4 to 7 are four to six queries. If after fifteen minutes there is no candidate, say so and escalate with the evidence collected, rather than guessing.
