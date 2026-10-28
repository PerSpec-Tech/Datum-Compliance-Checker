using System.Text.Json;
using System.Text.Json.Serialization;

namespace ComplianceChecker.Core.Live;

// The live pack (schemas/live-pack.schema.json): the rule engine's limits for one project as
// numbers and geometry. These small records mirror the schema for the live engine only; the
// LiveEngineTests parse the Python-side golden pack, so a schema change that breaks them fails a test.

public sealed record LivePack(
    [property: JsonPropertyName("project_id")] string ProjectId,
    [property: JsonPropertyName("model_version")] string ModelVersion,
    [property: JsonPropertyName("report_id")] string ReportId,
    [property: JsonPropertyName("edges")] List<EdgeMargin> Edges,
    [property: JsonPropertyName("envelope")] List<double[]>? Envelope,
    [property: JsonPropertyName("fsi")] FsiBudget Fsi,
    [property: JsonPropertyName("height")] HeightSamples Height,
    [property: JsonPropertyName("thresholds")] List<Threshold> Thresholds,
    [property: JsonPropertyName("notes")] List<string> Notes)
{
    public static LivePack FromJson(string json) =>
        JsonSerializer.Deserialize<LivePack>(json) ?? throw new JsonException("empty live pack");
}

public sealed record EdgeMargin(
    [property: JsonPropertyName("edge_id")] string EdgeId,
    [property: JsonPropertyName("a")] double[] A,
    [property: JsonPropertyName("b")] double[] B,
    [property: JsonPropertyName("kind")] string? Kind,
    [property: JsonPropertyName("margin_m")] double? MarginM,
    [property: JsonPropertyName("rule_id")] string? RuleId,
    [property: JsonPropertyName("clause_ref")] string? ClauseRef,
    [property: JsonPropertyName("margin_by_height")] List<double?> MarginByHeight);

public sealed record FsiBudget(
    [property: JsonPropertyName("plot_area_m2")] double? PlotAreaM2,
    [property: JsonPropertyName("base")] double? Base,
    [property: JsonPropertyName("max")] double? Max,
    [property: JsonPropertyName("base_built_up_m2")] double? BaseBuiltUpM2,
    [property: JsonPropertyName("max_built_up_m2")] double? MaxBuiltUpM2,
    [property: JsonPropertyName("used_m2")] double? UsedM2);

public sealed record HeightSamples(
    [property: JsonPropertyName("current_m")] double? CurrentM,
    [property: JsonPropertyName("step_m")] double StepM,
    [property: JsonPropertyName("max_m")] double MaxM,
    [property: JsonPropertyName("limit_m")] double? LimitM = null,
    [property: JsonPropertyName("limit_clause_ref")] string? LimitClauseRef = null);

public sealed record Threshold(
    [property: JsonPropertyName("rule_id")] string RuleId,
    [property: JsonPropertyName("title")] string Title,
    [property: JsonPropertyName("clause_ref")] string ClauseRef,
    [property: JsonPropertyName("for_each")] string ForEach,
    [property: JsonPropertyName("field")] string Field,
    [property: JsonPropertyName("op")] string Op,
    [property: JsonPropertyName("limit")] double Limit,
    [property: JsonPropertyName("element_ids")] List<string> ElementIds,
    [property: JsonPropertyName("source_ids")] List<string?> SourceIds);
