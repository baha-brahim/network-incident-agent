---
id: RB-REPORT-WRITING
title: Incident report writing guide
tags: [report, writing, citations, evidence, timeline, confidence]
categories: []
---

# Incident report writing guide

## Overview

An incident report is read by people who were not in the investigation and may act on it. It must say what happened, why, how sure you are, and what to do, in that order, and it must let a reader check each claim. A short report with sourced facts is better than a long one with unsupported statements.

## Structure

1. **Summary.** Two or three sentences: what was affected, where, when, and the root cause.
2. **Root cause.** One category and one node, in plain words. State the time of the root cause event, which may precede the symptoms.
3. **Confidence.** High, medium or low, with the reason.
4. **Timeline.** Times in one stated time zone, with the root cause event, the alarms, the KPI onset, the recovery.
5. **Evidence.** A list. Each item names its source: an alarm id, a change id, a maintenance id, an event id, an anomaly id, a KPI query, or a runbook chunk id.
6. **Ruled out.** The competing hypotheses that were examined and why they were dropped.
7. **Recommended actions.** Specific, with an owner.

## Cite every claim

Every statement about the network must point at a record or a query result. "The link lost signal at 14:05" should reference the alarm id. "Sibling sites were unaffected" should reference the KPI query. If you cannot cite it, either find the evidence or remove the claim or mark it as inference.

## Root cause versus symptom

Separate the root cause from the symptom. A `SITE_DOWN` alarm is a symptom. A mains failure that preceded it by hours is the cause. Use the earliest event that explains the rest. When the cause precedes the KPI onset, say so in the timeline, and explain the delay.

## State what you ruled out

The most useful part of a report on a hard case is the set of hypotheses you set aside, with the evidence. Typical entries: a change that preceded the onset but with normal KPIs in between; a maintenance window that did not cover the failed node; an external event on a different day or site; a nuisance alarm that cleared with no KPI effect. If the right answer is "no incident, expected outage", say that clearly and cite the record that explains it.

## Calibrate confidence

- **High**: a direct hard alarm or record on the root cause node, the topology matches the affected set, and competing hypotheses were tested and rejected.
- **Medium**: the pattern fits and the alternatives were rejected, but a direct record is missing or late.
- **Low**: the pattern is plausible but evidence is thin. Say what would settle it.

A missing alarm is not evidence of absence. Say when a conclusion rests on KPIs alone.

## Quantify the impact

Give the number of sites or regions, the duration in hours and the size of the KPI change, for example "volume down about 30 percent for three hours". Do not exaggerate. If a figure is an estimate, say so.

## Style

Plain language, short sentences, no filler. Use full ids for nodes and records. Convert times to the local time zone and name it, or keep UTC and name that. Do not hide the uncertain parts. Do not recommend an action the evidence does not support.

## Self-check before sending

Is the root cause one node and one category? Does every evidence item cite a source? Are the times consistent and in one time zone? Did you test at least one alternative? Does the recommended action match the cause?
