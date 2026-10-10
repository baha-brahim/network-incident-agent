---
id: RB-ALARM-REFERENCE
title: Alarm reference
tags: [alarms, reference, severity, link-los, site-down, mains-failure, high-prb, temp-high]
categories: []
---

# Alarm reference

## Overview

Every alarm type that this network raises, what it means and how much weight it deserves. Alarms are in the `alarms` table with a node, a type, a severity (`critical`, `major`, `minor`, `warning`), a `raised_at` time and a `cleared_at` time. A NULL `cleared_at` means the alarm is still active. The same alarm type can be a serious sign or a nuisance depending on its severity and node.

## Transport alarms

- **`LINK_LOS`** (critical, on a transport link). Loss of signal: no light or no carrier on the uplink. All sites behind the link go down. Strong evidence of a cut or a planned splice. See the fiber cut and maintenance runbooks.
- **`LINK_DEGRADED`** (major or minor, on a link). A major alarm on a microwave link ("reduced modulation") means capacity loss and a service degradation. A minor alarm ("minor errored seconds, link still within SLA") is background noise and clears in minutes. On a fiber link a minor alarm with falling optical power can precede a cut.

## Power alarms

- **`MAINS_FAILURE`** (major, on a site). AC mains lost, the site is running on battery. KPIs stay normal until the battery is empty.
- **`BATTERY_LOW`** (major, on a site). The battery has about 15 minutes left. The site will go down.
- **`RECTIFIER_FAULT`** (minor, on a site). A power module fault. It may reduce autonomy. By itself it does not stop service.

## Site availability alarm

- **`SITE_DOWN`** (critical, on a site). The site is unreachable ("OAM heartbeat lost" or "power supply exhausted"). It is a symptom, not a cause. The cause is upstream (link, power) or planned (maintenance). Always find what raised it.

## Radio and accessibility alarms

- **`HIGH_PRB`** (warning, on a site). PRB utilisation above 85 or 90 percent. Raised during congestion and during large events. It does not say which.
- **`RRC_FAILURE_RATE_HIGH`** (minor, on a site). RRC setup failure rate above the threshold. Seen on some sites after a bad change, 15 to 45 minutes late. Few sites raise it even when many are affected.
- **`VSWR_HIGH`** (minor, on a site). Reflection on a sector antenna feeder. Frequent and usually harmless. If real, one sector degrades.

## Environmental alarms

- **`TEMP_HIGH`** (warning, on a site). Cabinet temperature high. Common on summer afternoons and flapping.
- **`FAN_FAILURE`** (minor, on a site). Cooling fan slow, may last hours. A maintenance item.
- **`DOOR_OPEN`** (warning, on a site). Cabinet door open, usually a visit.

## Core and router alarms

- **`DNS_TIMEOUT_RATE`** (major, on the DNS node). Timeout rate above 5 percent. Means DNS degradation. It can lag the onset by minutes to an hour, or never appear, so check `core_kpis`.
- **`CPU_HIGH`** (warning, on a router or core node). CPU load high. Brief spikes are normal. By itself it does not show an outage.

## Severity levels

- **critical**: service is lost for some users now.
- **major**: service is degraded or at imminent risk.
- **minor**: a fault that does not affect service yet.
- **warning**: a threshold crossing for information.

Weigh severity before count. Dozens of warnings from one site do not outrank one critical alarm on a shared link.

## Reading alarm timing

An alarm's `raised_at` is the earliest time you can place an event. A cause cannot be later than its symptom. Alarms with a delay (`DNS_TIMEOUT_RATE`, `RRC_FAILURE_RATE_HIGH`) should be dated from the KPI onset, not from the alarm.
