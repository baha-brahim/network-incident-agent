---
id: RB-CHANGE-CORRELATION
title: Change correlation policy
tags: [change, correlation, timing, decoy, rollback, policy, coincidence]
categories: [bad_change]
---

# Change correlation policy

## Overview

A change log is the first place people look and the most common source of wrong answers. A busy network logs one to three changes a day: tuning, patches, template pushes. Almost none cause a problem. So a change that happened some time before an incident is weak evidence. This policy sets when a change may be named as a cause and when it must be set aside.

## The base rate

With a couple of changes logged every day across the network, a randomly chosen hour has a good chance of a harmless change somewhere in the preceding hour or two. Finding one proves nothing. Treat a change as a coincidence unless it passes the tests below.

## Tests for naming a change as the cause

All of the following should hold.

1. **Location.** The change is on the affected nodes themselves, or on their common ancestor (the router or link above all of them). A change on an unrelated node is not a cause.
2. **Timing.** The KPI onset follows the change within one or two 15-minute steps. A configuration change takes effect immediately. A gap of 30 to 90 minutes with normal KPIs in between means the change did not do it.
3. **Shape.** The effect is what a configuration problem looks like: a step in RRC success, drop rate or volume, with availability intact. A change cannot explain outages with `LINK_LOS`, `MAINS_FAILURE` or maintenance windows.
4. **Control group.** Nodes outside the changed subtree stay normal.
5. **Reversal.** If a rollback exists, the KPIs recover at the time of the rollback. This is the strongest single piece of evidence.

## Setting a change aside

State why. Typical reasons: it ran 15 to 90 minutes before the onset and KPIs were normal in between; it was on one site while several siblings failed; it completed before a hard alarm that has its own explanation; its type is a routine upgrade with no KPI change at the time. Write this in the report as a ruled-out hypothesis with the change id.

## When a change precedes a real incident

It happens that a harmless change falls shortly before a real fault. In these cases the order is: find the hard evidence (alarm, availability, maintenance record), and then check whether the change could explain it. If a hard alarm sits at the onset and the change is earlier, the alarm wins.

## Descriptions

Do not decide from the text of the description. A scheduled optimisation batch can hide a damaging template, and a "security hotfix" can be harmless. Use location, timing, shape and reversal.

## Upgrades and tuning

Software upgrades often run at night and restart equipment, which can cause short availability dips at the time. Those are expected if the upgrade fits the time. A regression that persists after an upgrade is a separate matter; see the upgrade regression runbook. Parameter tuning is usually neutral. It matters only if its timing and shape fit.

## Rollbacks

A rollback is its own change row with `change_type` of `rollback`, pointing at the original through `rollback_of`, and the original has status `rolled_back`. The time between the two rows is the duration of the regression. Do not count the rollback as a cause.

## Reporting a change-based cause

Name the change id, the node, the execution time, the KPI step that followed, the rollback id and the recovery time. State the control group result.
