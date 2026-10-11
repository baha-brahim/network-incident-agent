import type { components } from "./api-schema";

type S = components["schemas"];

export type Recording = S["Recording"];
export type RunEvent = Recording["events"][number];
export type EventType = RunEvent["type"];
export type EventOf<T extends EventType> = Extract<RunEvent, { type: T }>;

export type Report = S["Report"];
export type Classification = Report["classification"];
export type Category = Report["root_cause_category"];
export type Confidence = Report["confidence"];
export type TimelineEntry = S["TimelineEntry"];
export type Finding = S["Finding"];
export type HypothesisEntry = S["HypothesisEntry"];
export type DismissedSignal = S["DismissedSignal"];

export type ScopeData = S["ScopeData"];
export type LlmCallData = S["LlmCallData"];
export type ToolCallData = S["ToolCallData"];
export type ToolResultData = S["ToolResultData"];
export type NoteData = S["NoteData"];
export type GateData = S["GateData"];
export type ErrorData = S["ErrorData"];
export type RunFinishedData = S["RunFinishedData"];
export type EvidenceItem = S["EvidenceItem"];
export type EvidenceEntry = S["EvidenceEntry"];
export type EvidenceKind = EvidenceItem["kind"];
export type UsageTotals = S["UsageTotals"];

export type Meta = S["Meta"];
export type DemoSummary = S["DemoSummary"];
export type InvestigationSummary = S["InvestigationSummary"];
export type InvestigationDetail = S["InvestigationDetail"];
export type AlertOut = S["AlertOut"];
export type KpiSeries = S["KpiSeries"];
