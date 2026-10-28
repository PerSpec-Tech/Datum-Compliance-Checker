using System.Text.Json;
using ComplianceChecker.Core.Model;
using ComplianceChecker.Generated;

namespace ComplianceChecker.Core.Tests;

public class ModelBuilderTests
{
    private static readonly DateTimeOffset Now = new(2026, 10, 19, 12, 0, 0, TimeSpan.Zero);

    /// <summary>A small G+1 house as the Revit exporter would report it (metres, already converted).</summary>
    internal static RawModel House() => new()
    {
        ProjectName = "Test house",
        SourceFile = "house.rvt",
        ToolVersion = "test",
        Latitude = 41.88, // a template default (Chicago), not Pune
        Longitude = -87.63,
        // Property lines drawn as loose segments, some reversed, starting anywhere.
        PropertyLineSegments = new()
        {
            (new Pt(15, 20), new Pt(15, 0)),
            (new Pt(0, 0), new Pt(15, 0)),
            (new Pt(0, 20), new Pt(15, 20)),
            (new Pt(0, 0), new Pt(0, 20)),
        },
        Footprint = new() { new(3, 4.5), new(3, 15), new(12, 15), new(12, 4.5) }, // clockwise on purpose
        GroundLevelM = 0,
        RoofTopM = 6.4,
        HighestPointM = 7.4,
        Levels = new() { new("L1", "u-l1", "First", 3.2), new("L0", "u-l0", "Ground", 0), new("LB", "u-lb", "Basement", -3) },
        Rooms = new()
        {
            new("R1", "u-r1", "Living Room", "L0", 31.5, 3.0, new() { new(3, 4.5), new(12, 4.5), new(12, 8), new(3, 8) }),
            new("R2", "u-r2", "Kitchen", "L0", 12, 2.7, null),
            new("R3", "u-r3", "Stair", "L0", 6, 3.0, null),
            new("R4", "u-r4", "Mystery 7", "L1", 10, null, null, "volume not computed"),
        },
        Areas = new()
        {
            new("A0", "u-a0", "Gross Building", "L0", "BUA Ground", 94.5),
            new("A1", "u-a1", "Rentable", "L0", "Rentable", 80),
            new("U1", "u-u1", "Units (carpet)", "L1", "Flat 101", 55),
            new("U2", "u-u2", "Units (carpet)", "L0", "Shop 1", 30),
        },
        Stairs = new() { new("S1", "u-s1", "L0", "L1", 0.9, 0.16, 0.28) },
        Doors = new()
        {
            new("D1", "u-d1", "L0", 1.0, 2.1, "R1", null),
            new("D2", "u-d2", "L0", 0.9, 2.1, "R1", "R3"),
            new("D3", "u-d3", "L0", 0.75, 2.1, "R1", "R2"),
        },
    };

    internal static Brief HouseBrief() => new()
    {
        Latitude = 18.4655,
        Longitude = 73.896,
        OccupancyGroup = "A",
        OccupancySubdivision = "A-2",
        Zone = "residential",
        CongestedArea = false,
        BuildingType = "bungalow_self_use",
        PlotAreaM2 = 300,
        MetroTod = false,
        Special = { ["heritage"] = false },
        Edges = { [Geometry.EdgeKey(new Pt(0, 0), new Pt(15, 0))] = new EdgeTag { Kind = "road", RoadWidthM = 9, Basis = "development_plan" } },
    };

    [Fact]
    public void Property_line_segments_chain_into_a_counter_clockwise_boundary_with_edges()
    {
        var m = ModelBuilder.Build(House(), new Brief(), Now);
        Assert.Equal(4, m.Site.Boundary.Count);
        Assert.Equal(4, m.Site.Edges.Count);
        var poly = m.Site.Boundary.Select(p => new Pt(p[0], p[1])).ToList();
        Assert.True(Geometry.SignedArea(poly) > 0);
        Assert.Equal(300, Geometry.Area(poly), 6);
        Assert.All(m.Site.Edges, e => Assert.Equal(Source.Default, e.Kind.Source));
    }

    [Fact]
    public void Declared_brief_facts_win_and_untagged_edges_stay_unknown()
    {
        var m = ModelBuilder.Build(House(), HouseBrief(), Now);
        Assert.Equal(Source.Declared, m.Project.Location.Source);
        Assert.Equal(18.4655, m.Project.Location.Value.Lat);
        Assert.Equal(BuildingType.BungalowSelfUse, m.Project.BuildingType.Value);
        Assert.Equal(OccupancyGroup.A, m.Project.Occupancy.Value.Group);
        Assert.Equal(300, m.Site.PlotAreaDeclaredM2.Value);
        Assert.False(m.Project.Special.Heritage.Value);
        Assert.Null(m.Project.Special.Coastal.Value); // not answered → unknown, not "no"

        var road = Assert.Single(m.Site.Edges, e => e.Kind.Value == EdgeKind.Road);
        Assert.Equal(9, road.RoadWidthM.Value);
        Assert.Equal(Source.Declared, road.RoadWidthM.Source);
        Assert.Equal(3, m.Site.Edges.Count(e => e.Kind.Value is null));
    }

    [Fact]
    public void Revit_location_without_a_brief_is_marked_model_with_a_warning()
    {
        var m = ModelBuilder.Build(House(), new Brief(), Now);
        Assert.Equal(Source.Model, m.Project.Location.Source);
        Assert.Contains("confirm", m.Project.Location.Note);
    }

    [Fact]
    public void Levels_are_sorted_and_basements_detected()
    {
        var m = ModelBuilder.Build(House(), new Brief(), Now);
        Assert.Equal(new[] { "LB", "L0", "L1" }, m.Levels.Select(l => l.Id));
        Assert.True(m.Levels[0].IsBasement);
        Assert.False(m.Levels[1].IsBasement);
    }

    [Fact]
    public void Footprint_is_normalised_counter_clockwise()
    {
        var m = ModelBuilder.Build(House(), new Brief(), Now);
        var fp = m.Building.Footprint.Select(p => new Pt(p[0], p[1])).ToList();
        Assert.True(Geometry.SignedArea(fp) > 0);
        Assert.Equal(94.5, Geometry.Area(fp), 6);
    }

    [Fact]
    public void Areas_split_into_fsi_areas_and_units()
    {
        var m = ModelBuilder.Build(House(), new Brief(), Now);
        Assert.Equal(new[] { "A0", "A1" }, m.Areas.Select(a => a.Id));
        Assert.True(m.Areas[0].CountsToFar.Value); // Gross Building
        Assert.Null(m.Areas[1].CountsToFar.Value); // Rentable: unknown, so the engine asks
        Assert.Equal(new[] { "U1", "U2" }, m.Units.Select(u => u.Id));
        Assert.Equal(UnitUse.Residential, m.Units[0].Use.Value);
        Assert.Equal(UnitUse.Commercial, m.Units[1].Use.Value);
    }

    [Fact]
    public void Room_uses_are_guessed_from_names_or_left_unknown()
    {
        var m = ModelBuilder.Build(House(), new Brief(), Now);
        Assert.Equal(Usage.Living, m.Spaces[0].Usage.Value);
        Assert.Equal(Usage.Kitchen, m.Spaces[1].Usage.Value);
        Assert.Equal(Source.Inferred, m.Spaces[0].Usage.Source);
        Assert.Null(m.Spaces[3].Usage.Value);
        Assert.Equal(Source.Default, m.Spaces[3].Usage.Source);
    }

    [Fact]
    public void Exit_doors_are_inferred_from_rooms()
    {
        var m = ModelBuilder.Build(House(), new Brief(), Now);
        Assert.True(m.Doors[0].IsExit.Value); // to outside
        Assert.True(m.Doors[1].IsExit.Value); // into the stair
        Assert.False(m.Doors[2].IsExit.Value); // living → kitchen
        Assert.All(m.Doors, d => Assert.Equal(Source.Inferred, d.IsExit.Source));
    }

    [Fact]
    public void Brief_round_trips_through_json()
    {
        var b = HouseBrief();
        var back = Brief.FromJson(b.ToJson());
        Assert.Equal(b.ToJson(), back.ToJson());
        Assert.Contains("\"road_width_m\":9", b.ToJson());
        Assert.Equal("{\"version\":1,\"special\":{},\"edges\":{}}", new Brief().ToJson());
        Assert.NotNull(Brief.FromJson(null));
    }

    [Fact]
    public void Writes_a_sample_export_for_the_python_schema_check()
    {
        var json = ModelBuilder.Build(House(), HouseBrief(), Now).ToJson();
        using var doc = JsonDocument.Parse(json);
        Assert.Equal("1.0", doc.RootElement.GetProperty("schema_version").GetString());
        Assert.Equal("revit", doc.RootElement.GetProperty("meta").GetProperty("source_kind").GetString());
        // `just test-addin` validates this file against schemas/building-model.schema.json.
        string outDir = Path.Combine(RepoRoot(), "revit-addin", "tests", "out");
        Directory.CreateDirectory(outDir);
        File.WriteAllText(Path.Combine(outDir, "sample_export.json"), json);
    }

    [Fact]
    public void Python_fixtures_parse_into_the_csharp_contract()
    {
        foreach (var name in new[] { "compliant_house", "violating_apartment", "missing_site" })
        {
            var json = File.ReadAllText(Path.Combine(RepoRoot(), "fixtures", "models", name + ".json"));
            var m = BuildingModel.FromJson(json);
            Assert.NotNull(m.Project);
            Assert.NotEmpty(m.Levels);
        }
    }

    internal static string RepoRoot()
    {
        var dir = new DirectoryInfo(AppContext.BaseDirectory);
        while (dir is not null && !File.Exists(Path.Combine(dir.FullName, "justfile")))
            dir = dir.Parent;
        return dir?.FullName ?? throw new InvalidOperationException("repo root not found");
    }
}

public class GeometryTests
{
    [Fact]
    public void Chain_rejects_open_or_broken_loops()
    {
        Assert.Null(Geometry.ChainLoop(new List<(Pt, Pt)> { (new(0, 0), new(1, 0)), (new(1, 0), new(1, 1)), (new(1, 1), new(0, 2)) }));
        Assert.Null(Geometry.ChainLoop(new List<(Pt, Pt)> { (new(0, 0), new(1, 0)) }));
    }

    [Fact]
    public void Edge_key_is_order_independent_and_rounded()
    {
        Assert.Equal(Geometry.EdgeKey(new(0, 0), new(15, 0)), Geometry.EdgeKey(new(15.004, 0), new(0, 0.003)));
        Assert.Equal("7.5,0.0", Geometry.EdgeKey(new(0, 0), new(15, 0)));
    }
}
