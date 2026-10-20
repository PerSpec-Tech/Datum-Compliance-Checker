using System.Text.Json;
using System.Text.Json.Serialization;

namespace ComplianceChecker.Core.Model;

/// <summary>
/// Facts the architect declares in Site Setup (D5): legal facts that geometry can't give.
/// Stored as JSON in the model's Extensible Storage (D11), so it travels with the .rvt file.
/// Everything here becomes a Fact with source "declared", which always wins.
/// </summary>
public sealed class Brief
{
    public int Version { get; set; } = 1;

    /// <summary>Server-side project id, so re-checks update the same project.</summary>
    public string? ProjectId { get; set; }

    public double? Latitude { get; set; }
    public double? Longitude { get; set; }

    /// <summary>NBC Part 4 group, e.g. "A".</summary>
    public string? OccupancyGroup { get; set; }
    /// <summary>e.g. "A-4", as printed in the source.</summary>
    public string? OccupancySubdivision { get; set; }

    public string? Zone { get; set; }
    public bool? CongestedArea { get; set; }
    /// <summary>group_housing | standalone | bungalow_self_use | mixed_use | other</summary>
    public string? BuildingType { get; set; }

    public double? PlotAreaM2 { get; set; }
    public bool? IsCornerPlot { get; set; }
    public bool? MetroTod { get; set; }
    public double? PlotShareInTod { get; set; }

    /// <summary>heritage, coastal, airport_zone, ht_line, railway, river_flood_line, hill_slope_bdp,
    /// defence_vicinity, metro_rail_within_20m → yes/no.</summary>
    public Dictionary<string, bool> Special { get; set; } = new();

    /// <summary>Plot edge tags, keyed by <see cref="Geometry.EdgeKey"/>.</summary>
    public Dictionary<string, EdgeTag> Edges { get; set; } = new();

    public static readonly JsonSerializerOptions JsonOptions = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
        DefaultIgnoreCondition = JsonIgnoreCondition.WhenWritingNull,
        WriteIndented = false,
    };

    public string ToJson() => JsonSerializer.Serialize(this, JsonOptions);

    public static Brief FromJson(string? json) =>
        string.IsNullOrWhiteSpace(json) ? new Brief() : JsonSerializer.Deserialize<Brief>(json, JsonOptions) ?? new Brief();
}

public sealed class EdgeTag
{
    /// <summary>road | neighbour | open_space</summary>
    public string? Kind { get; set; }
    public double? RoadWidthM { get; set; }
    /// <summary>existing | development_plan</summary>
    public string? Basis { get; set; }
}
