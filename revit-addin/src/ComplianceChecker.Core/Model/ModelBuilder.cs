using System.Text.RegularExpressions;
using ComplianceChecker.Generated;

// The generated contract types are not null-annotated, but the schema allows null in many places
// (e.g. "source_id": null, "boundary": null). Assigning null to them is intended here.
#pragma warning disable CS8601, CS8625

namespace ComplianceChecker.Core.Model;

/// <summary>
/// Turns what the exporter read (<see cref="RawModel"/>) plus the declared <see cref="Brief"/> into the
/// BuildingModel contract (schemas/building-model.schema.json). Every fact records where it came from:
/// model (measured), inferred (guessed, to be confirmed), declared (the architect said so) or default
/// (unknown). Unknowns stay null so the engine reports "cannot verify" instead of guessing (D4).
/// </summary>
public static class ModelBuilder
{
    private static readonly Regex UnitScheme = new("unit|carpet|tenement|flat", RegexOptions.IgnoreCase);
    private static readonly Regex FsiScheme = new("gross|fsi|bua|built", RegexOptions.IgnoreCase);
    private static readonly Regex Commercial = new("shop|retail|commercial|showroom", RegexOptions.IgnoreCase);
    private static readonly Regex Office = new("office", RegexOptions.IgnoreCase);

    public static readonly string[] SpecialKeys =
    {
        "heritage", "coastal", "airport_zone", "ht_line", "railway", "river_flood_line",
        "hill_slope_bdp", "defence_vicinity", "metro_rail_within_20m",
    };

    public static BuildingModel Build(RawModel raw, Brief brief, DateTimeOffset now)
    {
        var boundary = Geometry.ChainLoop(raw.PropertyLineSegments);
        double? ground = raw.GroundLevelM;
        var roomUsage = new Dictionary<string, FactUsage>();

        var model = new BuildingModel
        {
            SchemaVersion = SchemaVersion.The10,
            Meta = new Meta
            {
                SourceKind = SourceKind.Revit,
                SourceFile = raw.SourceFile,
                ExportedAt = now,
                ToolVersion = raw.ToolVersion,
            },
            Project = BuildProject(raw, brief),
            Site = BuildSite(boundary, brief, ground),
            Levels = raw.Levels
                .OrderBy(l => l.ElevationM)
                .Select(l => new Level
                {
                    Id = l.Id,
                    SourceId = l.UniqueId,
                    Name = l.Name,
                    ElevationM = Math.Round(l.ElevationM, 4),
                    IsBasement = ground is double g && l.ElevationM < g - Geometry.Tolerance,
                })
                .ToList(),
            Building = new Building
            {
                Footprint = raw.Footprint is { Count: >= 3 } fp ? Geometry.ToJson(Geometry.Normalise(fp)) : null,
                RoofTopM = Round(raw.RoofTopM),
                HighestPointM = Round(raw.HighestPointM),
            },
            Spaces = raw.Rooms
                .Select(r =>
                {
                    var usage = UsageGuess.Guess(r.Name);
                    roomUsage[r.Id] = usage;
                    var poly = r.Polygon is { Count: >= 3 } p ? Geometry.Normalise(p) : null;
                    return new Space
                    {
                        Id = r.Id,
                        SourceId = r.UniqueId,
                        Name = r.Name,
                        LevelId = r.LevelId,
                        Usage = usage,
                        AreaM2 = Round(r.AreaM2),
                        ClearHeightM = Round(r.ClearHeightM),
                        Polygon = poly is { Count: >= 3 } ? Geometry.ToJson(poly) : null,
                    };
                })
                .ToList(),
            Areas = raw.Areas.Where(a => !UnitScheme.IsMatch(a.Scheme)).Select(BuildArea).ToList(),
            Units = raw.Areas.Where(a => UnitScheme.IsMatch(a.Scheme)).Select(BuildUnit).ToList(),
            Stairs = raw.Stairs
                .Select(s => new Stair
                {
                    Id = s.Id,
                    SourceId = s.UniqueId,
                    BaseLevelId = s.BaseLevelId,
                    TopLevelId = s.TopLevelId,
                    MinRunWidthM = Round(s.MinRunWidthM),
                    RiserM = Round(s.RiserM),
                    TreadM = Round(s.TreadM),
                    IsExit = new FactBool { Value = true, Source = Source.Inferred, Confidence = 0.6, Note = "staircases assumed to be exit routes" },
                })
                .ToList(),
            Doors = raw.Doors.Select(d => BuildDoor(d, roomUsage)).ToList(),
        };
        return model;
    }

    private static Project BuildProject(RawModel raw, Brief brief)
    {
        FactLatLon location;
        if (brief.Latitude is double lat && brief.Longitude is double lon)
            location = new FactLatLon { Value = new LatLon { Lat = lat, Lon = lon }, Source = Source.Declared };
        else if (raw.Latitude is double rlat && raw.Longitude is double rlon)
            location = new FactLatLon
            {
                Value = new LatLon { Lat = Math.Round(rlat, 6), Lon = Math.Round(rlon, 6) },
                Source = Source.Model,
                Note = "Revit project location; confirm it in Site Setup (templates often default to another city)",
            };
        else
            location = new FactLatLon { Value = null, Source = Source.Default };

        return new Project
        {
            Name = string.IsNullOrWhiteSpace(raw.ProjectName) ? "Untitled" : raw.ProjectName,
            Location = location,
            AuthorityId = new FactString { Value = null, Source = Source.Default, Note = "resolved by the server from the location" },
            Rulesets = new FactStringList { Value = null, Source = Source.Default, Note = "resolved by the server from the location" },
            Occupancy = brief.OccupancyGroup is { } g && Enum.TryParse<OccupancyGroup>(g, true, out var group)
                ? new FactOccupancy { Value = new Occupancy { Group = group, Subdivision = brief.OccupancySubdivision }, Source = Source.Declared }
                : new FactOccupancy { Value = null, Source = Source.Default },
            Zone = Declared(brief.Zone),
            CongestedArea = Declared(brief.CongestedArea),
            BuildingType = new FactBuildingType
            {
                Value = Parse<BuildingType>(brief.BuildingType),
                Source = brief.BuildingType is null ? Source.Default : Source.Declared,
            },
            Special = new Special
            {
                Heritage = SpecialFact(brief, "heritage"),
                Coastal = SpecialFact(brief, "coastal"),
                AirportZone = SpecialFact(brief, "airport_zone"),
                HtLine = SpecialFact(brief, "ht_line"),
                Railway = SpecialFact(brief, "railway"),
                RiverFloodLine = SpecialFact(brief, "river_flood_line"),
                HillSlopeBdp = SpecialFact(brief, "hill_slope_bdp"),
                DefenceVicinity = SpecialFact(brief, "defence_vicinity"),
                MetroRailWithin20M = SpecialFact(brief, "metro_rail_within_20m"),
            },
            Overlays = new Overlays
            {
                NearestMetroStation = new FactMetroStation { Value = null, Source = Source.Default, Note = "inferred by the server from station data" },
                MetroTod = Declared(brief.MetroTod),
                PlotShareInTod = Declared(brief.PlotShareInTod),
            },
        };
    }

    private static Site BuildSite(List<Pt>? boundary, Brief brief, double? ground)
    {
        var edges = new List<Edge>();
        if (boundary is not null)
        {
            for (int i = 0; i < boundary.Count; i++)
            {
                Pt a = boundary[i], b = boundary[(i + 1) % boundary.Count];
                brief.Edges.TryGetValue(Geometry.EdgeKey(a, b), out var tag);
                edges.Add(new Edge
                {
                    Id = $"e{i + 1}",
                    A = new List<double> { Math.Round(a.X, 4), Math.Round(a.Y, 4) },
                    B = new List<double> { Math.Round(b.X, 4), Math.Round(b.Y, 4) },
                    Kind = new FactEdgeKind { Value = Parse<EdgeKind>(tag?.Kind), Source = tag?.Kind is null ? Source.Default : Source.Declared },
                    RoadWidthM = Declared(tag?.RoadWidthM),
                    RoadWidthBasis = new FactRoadWidthBasis
                    {
                        Value = Parse<RoadWidthBasis>(tag?.Basis),
                        Source = tag?.Basis is null ? Source.Default : Source.Declared,
                    },
                });
            }
        }
        return new Site
        {
            Boundary = boundary is null ? null : Geometry.ToJson(boundary),
            PlotAreaDeclaredM2 = Declared(brief.PlotAreaM2),
            IsCornerPlot = Declared(brief.IsCornerPlot),
            GroundLevelM = Round(ground),
            Edges = edges,
        };
    }

    private static Area BuildArea(RawArea a) => new()
    {
        Id = a.Id,
        SourceId = a.UniqueId,
        Scheme = a.Scheme,
        LevelId = a.LevelId,
        Name = a.Name,
        AreaM2 = Round(a.AreaM2),
        CountsToFar = FsiScheme.IsMatch(a.Scheme)
            ? new FactBool { Value = true, Source = Source.Model, Note = $"area scheme '{a.Scheme}' is the FSI / built-up scheme" }
            : new FactBool { Value = null, Source = Source.Default, Note = $"does area scheme '{a.Scheme}' count towards FSI?" },
    };

    private static Unit BuildUnit(RawArea a)
    {
        UnitUse use = Commercial.IsMatch(a.Name) ? UnitUse.Commercial : Office.IsMatch(a.Name) ? UnitUse.Office : UnitUse.Residential;
        return new Unit
        {
            Id = a.Id,
            SourceId = a.UniqueId,
            Name = a.Name,
            LevelId = a.LevelId,
            CarpetAreaM2 = Round(a.AreaM2),
            Use = new FactUnitUse { Value = use, Source = Source.Inferred, Confidence = 0.6, Note = "from the area name" },
        };
    }

    private static Door BuildDoor(RawDoor d, Dictionary<string, FactUsage> roomUsage)
    {
        bool exterior = d.FromRoomId is null || d.ToRoomId is null;
        bool toStair = new[] { d.FromRoomId, d.ToRoomId }
            .Any(id => id is not null && roomUsage.TryGetValue(id, out var u) && u.Value == Usage.Stair);
        FactBool isExit = exterior
            ? new FactBool { Value = true, Source = Source.Inferred, Confidence = 0.7, Note = "door to the outside" }
            : toStair
                ? new FactBool { Value = true, Source = Source.Inferred, Confidence = 0.6, Note = "door into a staircase" }
                : new FactBool { Value = false, Source = Source.Inferred, Confidence = 0.6, Note = "internal door" };
        return new Door
        {
            Id = d.Id,
            SourceId = d.UniqueId,
            LevelId = d.LevelId,
            WidthM = Round(d.WidthM),
            HeightM = Round(d.HeightM),
            IsExit = isExit,
            FromSpaceId = d.FromRoomId,
            ToSpaceId = d.ToRoomId,
        };
    }

    private static FactBool SpecialFact(Brief brief, string key) =>
        brief.Special.TryGetValue(key, out bool v)
            ? new FactBool { Value = v, Source = Source.Declared }
            : new FactBool { Value = null, Source = Source.Default };

    private static FactString Declared(string? v) =>
        new() { Value = string.IsNullOrWhiteSpace(v) ? null : v, Source = string.IsNullOrWhiteSpace(v) ? Source.Default : Source.Declared };

    private static FactBool Declared(bool? v) => new() { Value = v, Source = v is null ? Source.Default : Source.Declared };

    private static FactNumber Declared(double? v) => new() { Value = v, Source = v is null ? Source.Default : Source.Declared };

    private static double? Round(double? v) => v is double d ? Math.Round(d, 4) : null;

    /// <summary>Parse a snake_case schema value ("bungalow_self_use") into the generated enum.</summary>
    private static T? Parse<T>(string? value) where T : struct, Enum =>
        value is not null && Enum.TryParse<T>(value.Replace("_", ""), ignoreCase: true, out var e) ? e : null;
}
