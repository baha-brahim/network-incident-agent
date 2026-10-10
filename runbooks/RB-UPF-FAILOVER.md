---
id: RB-UPF-FAILOVER
title: UPF failover
tags: [upf, failover, user-plane, sessions, throughput, core, redundancy]
categories: []
---

# UPF failover

## Overview

A user plane function (UPF) carries the data traffic of the regions it serves. When a UPF instance fails or is taken out of service, its traffic switches to a standby instance. During the switch, established sessions are dropped, devices re-establish them, and throughput dips for a short period. After the failover, service continues on the standby. If the standby is smaller or the switch fails, the degradation lasts longer.

## Signature in the data

- **One UPF, its regions only.** `throughput_gbps` and `session_count` on one UPF node fall sharply and then recover, while the other UPF is normal. Each UPF serves two regions, so those two regions show the effect together.
- **Session count resets.** `session_count` falls to a low value and climbs back over minutes as devices reconnect.
- **Cell KPIs.** Volume in the served regions dips for the same period. `rrc_success_pct` is normal, since radio access is fine. Availability is 100.
- **Quality after the switch.** Latency may be slightly higher if the standby is at a different location.
- **Alarms.** Core alarms for the failed instance. This alarm set does not model them.
- **Duration.** Usually minutes. Longer if the failover fails.

## Differential diagnosis

### Versus DNS degradation

DNS trouble affects all regions and raises latency. A UPF failover affects only the two regions of that UPF and shows up in UPF metrics, with latency unchanged.

### Versus a regional transport failure

Transport failures zero availability at specific sites. A UPF event leaves availability at 100 and lowers volume across both regions for a short time.

### Versus an AMF storm

The AMF shows in `attach_success_pct`. The UPF shows in `throughput_gbps` and `session_count`.

### Versus a region-wide bad change

A change is tied to a change record and a router subtree and lasts hours until rolled back. A failover is short, has no change on the subtree, and affects the UPF's regions evenly.

### Versus a holiday

A holiday lowers traffic across all regions for a day without a sudden step in session count.

## Verification steps

1. Compare `throughput_gbps` and `session_count` of both UPF nodes. Only one should be affected.
2. Check which regions that UPF serves, in the node attributes, and confirm those regions' volumes dipped.
3. Confirm that availability stayed at 100 percent.
4. Check for core changes or maintenance on the UPF.
5. Look at the time to recovery, to see whether the standby restored the previous level.

## Recommended actions

Confirm that the standby is carrying the full load and that capacity headroom is adequate. Review the cause of the primary failure with the core team. Run a failback in a maintenance window if the design requires it. Test the failover regularly.

## Escalation

Core operations own the case. Severity is medium for a short dip and high if both regions stayed degraded beyond fifteen minutes. Tell customer care that sessions were reset, and ask the vendor for a root-cause analysis if the failover did not complete cleanly.
