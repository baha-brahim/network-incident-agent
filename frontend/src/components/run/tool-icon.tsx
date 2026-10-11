import {
  BellRing,
  BookOpenText,
  CalendarClock,
  ChartLine,
  Database,
  GitCompareArrows,
  Network,
  PartyPopper,
  Radar,
  Wrench,
  type LucideIcon,
} from "lucide-react";

const TOOL_ICONS: Record<string, LucideIcon> = {
  get_anomalies: Radar,
  get_alarms: BellRing,
  get_topology: Network,
  query_kpis: ChartLine,
  get_maintenance: CalendarClock,
  get_changes: GitCompareArrows,
  get_external_events: PartyPopper,
  search_runbooks: BookOpenText,
  run_sql: Database,
};

export function ToolIcon({ tool, className }: { tool: string; className?: string }) {
  const Icon = TOOL_ICONS[tool] ?? Wrench;
  return <Icon aria-hidden className={className} />;
}
