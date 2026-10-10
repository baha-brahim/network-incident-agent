---
id: RB-AMF-SIGNALLING-STORM
title: Signalling storm on the AMF
tags: [amf, signalling, attach, storm, registration, core, overload]
categories: []
---

# Signalling storm on the AMF

## Overview

The AMF handles registration, attach and mobility signalling for every device in the network. A signalling storm is a flood of registration or paging messages, often from a large group of devices that reconnect at once, such as after a regional outage, from a faulty device firmware or from misbehaving IoT devices. The AMF becomes overloaded and starts rejecting attach requests. Users cannot register, and new sessions fail while existing sessions keep running.

## Signature in the data

- **Attach success falls.** `attach_success_pct` on the AMF node drops from its normal level of about 99.5 percent to a lower value, with larger swings during the storm.
- **Connection setup suffers everywhere.** `rrc_success_pct` may fall together in several regions, since attach failures are seen as access failures.
- **Core load.** A `CPU_HIGH` warning on the AMF node, or on the aggregation routers carrying signalling.
- **Existing sessions are fine.** Established data transfer continues, so `dl_volume_mb` falls only moderately, and latency is not much affected.
- **Trigger.** The storm often begins right after another event, such as the recovery of a failed region, where thousands of devices reattach.
- **Alarms.** Core overload alarms, which this alarm set does not model beyond `CPU_HIGH`.

## Differential diagnosis

### Versus DNS degradation

DNS trouble raises latency and lowers volume, with RRC unaffected. An AMF storm lowers attach and setup success, with latency mostly unchanged. Check which core metric moved: `query_success_pct` and `resolution_ms` for DNS, `attach_success_pct` for the AMF.

### Versus a bad change

A change is scoped to a router or site group and starts at the change time. An AMF storm is nationwide or across several regions and follows a trigger, not a change record, unless the change was on the AMF.

### Versus recovery from a regional outage

A burst of attaches after an outage ends is the expected reattachment wave. It becomes a storm only if the AMF cannot cope and attach success stays low for a long time.

### Versus UPF trouble

A UPF fault lowers throughput and session counts for the regions it serves, with attach success normal.

### Versus a normal fluctuation

`attach_success_pct` has small noise around 99.5. Only a sustained deviation counts.

## Verification steps

1. Query the AMF node's `attach_success_pct` over the incident window.
2. Check `rrc_success_pct` by region, to see if it moved in several regions together.
3. Look for a trigger event: an outage that ended just before, or a software push to devices.
4. Check `get_alarms` on core nodes and `get_changes` on the AMF.

## Recommended actions

Core operations apply overload control: throttle or reject low-priority registrations, enable back-off timers on devices, and raise the AMF capacity if possible. Identify the offending device group and block or rate-limit it. Review the capacity of the signalling plane.

## Escalation

Core operations immediately; severity high if more than one region is affected. Involve the device or IoT platform owner for rogue devices.
