---
id: RB-RAN-UPGRADE-REGRESSION
title: RAN software upgrade regression
tags: [upgrade, software, regression, handover, restart, baseband, version]
categories: []
---

# RAN software upgrade regression

## Overview

A software upgrade on radio equipment replaces the running software on the baseband or radio units. Upgrades are usually run at night, require a restart of a few minutes, and are logged as a `software_upgrade` change. A regression happens when the new version behaves worse than the old one: handovers fail more, a feature stops working, or the unit restarts repeatedly. Unlike a configuration push, the fix is a software rollback or a patch from the vendor, which takes longer.

## Signature in the data

- **A software upgrade change** on a site or group of sites, executed at night. A short availability dip during the restart is expected, typically one or two steps.
- **Persistent quality loss after the restart.** Elevated `drop_rate_pct`, lower `rrc_success_pct`, and sometimes a lower volume that does not recover on the following days. This is the difference from a config push, which is tied to a template and reverses at once.
- **Version-specific.** Only sites that received the new software are affected. Sites still on the old version are normal.
- **Repeated restarts.** Several availability dips of a single step at different times of day on upgraded sites.
- **Alarms.** Possibly `RRC_FAILURE_RATE_HIGH` or equipment alarms. Not always.

## Differential diagnosis

### Versus the harmless upgrades

Most upgrades produce nothing more than a brief dip in availability during the restart. A software change only becomes a suspect if quality is worse after the restart than before it, on the upgraded sites only.

### Versus a bad configuration push

A configuration regression starts exactly at the change time without a restart, affects a router subtree or site group, and ends at a rollback record. An upgrade regression starts after the restart, tracks the software version, and may last days.

### Versus congestion or events

Those have high PRB and a user surge, and are not tied to a version.

### Versus interference

Interference is by sector and has a daily rhythm. An upgrade regression follows the list of upgraded nodes.

### Versus a hardware fault

A hardware fault affects individual units without regard to version. An upgrade regression follows the version.

## Verification steps

1. List `software_upgrade` changes in the last week and the nodes they touched.
2. Compare the quality KPIs of upgraded and non-upgraded sites before and after.
3. Check the restart steps for a dip in availability.
4. Look for repeated single-step dips after the upgrade.
5. Check the vendor release notes for known issues.

## Recommended actions

Pause the rollout of the same version to other sites. Roll back the affected sites to the previous software version, if the vendor allows. Open a vendor ticket with the evidence. Resume after a patch has been verified on a few canary sites.

## Escalation

RAN operations and the vendor. Severity depends on the number of upgraded sites and on how much their quality has fallen. Involve change management to hold further upgrades until the vendor confirms a fix, and tell customer care which areas run the new version.
