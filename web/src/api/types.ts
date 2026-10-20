// Re-exports of the generated contract types (schemas/*.schema.json → web/src/generated) plus the
// small aliases the UI uses. Edit the schema and run `just codegen`, never the generated file.
export type {
  BuildingModel,
  CheckReport,
  Clause,
  Edge,
  EdgeKind,
  FactUsed,
  FixBy,
  Freshness,
  FsiSummary,
  Question,
  Result,
  RoadWidthBasis,
  RuleStatus,
  Severity,
  Source,
  Status,
} from "../generated/contracts";

import type { Source } from "../generated/contracts";

export interface Fact<T> {
  value: T | null;
  source: Source;
  note?: string | null;
  confidence?: number | null;
}
