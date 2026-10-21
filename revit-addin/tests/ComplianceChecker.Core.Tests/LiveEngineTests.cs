using System.Text.Json;
using ComplianceChecker.Core.Live;
using ComplianceChecker.Core.Model;
using Xunit;

namespace ComplianceChecker.Core.Tests;

/// <summary>P9.2: the live engine on the Python-side golden live pack and the demo apartment.</summary>
public class LiveEngineTests
{
    private static LivePack Pack() => LivePack.FromJson(File.ReadAllText(
        Path.Combine(ModelBuilderTests.RepoRoot(), "fixtures", "expected", "demo_apartment.live-pack.json")));

    /// <summary>What Revit would measure for the demo apartment, moved by (dx, dy) metres.</summary>
    private static LiveSnapshot Snapshot(double dx = 0, double dy = 0, double? height = null)
    {
        using var doc = JsonDocument.Parse(File.ReadAllText(
            Path.Combine(ModelBuilderTests.RepoRoot(), "fixtures", "models", "demo_apartment.json")));
        JsonElement m = doc.RootElement;
        var snap = new LiveSnapshot
        {
            HeightM = height ?? m.GetProperty("building").GetProperty("roof_top_m").GetDouble(),
            BuiltUpM2 = m.GetProperty("areas").EnumerateArray().Sum(a => a.GetProperty("area_m2").GetDouble()),
        };
        var fp = m.GetProperty("building").GetProperty("footprint").EnumerateArray()
            .Select(p => new Pt(p[0].GetDouble() + dx, p[1].GetDouble() + dy)).ToList();
        snap.Outlines.Add(new LiveOutline("footprint", "ground floor slab", fp));

        void Values(string collection, params string[] fields)
        {
            foreach (JsonElement e in m.GetProperty(collection).EnumerateArray())
            {
                var d = new Dictionary<string, double?>();
                foreach (string f in fields)
                    d[f] = e.GetProperty(f).ValueKind == JsonValueKind.Number ? e.GetProperty(f).GetDouble() : null;
                snap.Values[e.GetProperty("source_id").GetString()!] = d;
            }
        }
        Values("spaces", "clear_height_m");
        Values("doors", "width_m", "height_m");
        Values("stairs", "min_run_width_m", "riser_m", "tread_m");
        return snap;
    }

    [Fact]
    public void Golden_pack_parses()
    {
        LivePack p = Pack();
        Assert.Equal(4, p.Edges.Count);
        Assert.NotNull(p.Envelope);
        Assert.Equal(2500.0, p.Fsi.MaxBuiltUpM2);
        Assert.NotEmpty(p.Thresholds);
    }

    [Fact]
    public void Finds_the_planted_setback_and_size_issues()
    {
        LiveStatus s = LiveEngine.Evaluate(Pack(), Snapshot());
        Assert.Equal(new[] { "e1", "e2" }, s.Setbacks.Select(x => x.EdgeId).OrderBy(x => x).ToArray());
        SetbackIssue front = s.Setbacks.Single(x => x.EdgeId == "e1");
        Assert.Equal(0.5, front.DeficitM, 3);
        Assert.Equal("Table No. 6-D (Regulation 6.2.1)", front.ClauseRef);
        Assert.Equal(new[] { "udcpr2020.ch9.exit-door-width", "udcpr2020.ch9.habitable-height-min",
                             "udcpr2020.ch9.shop-height-min", "udcpr2020.ch9.stair-width-residential" },
            s.Thresholds.Select(t => t.RuleId).OrderBy(x => x).ToArray());
        Assert.Equal(-80.6, s.FsiLeftM2!.Value, 1);
        Assert.Contains("80 m² over", s.StripText().Replace("81", "80"));
    }

    [Fact]
    public void Moving_the_building_clears_the_setbacks()
    {
        LiveStatus s = LiveEngine.Evaluate(Pack(), Snapshot(dx: -0.35, dy: 0.6));
        Assert.Empty(s.Setbacks);
        Assert.Contains("margins ✓", s.StripText());
    }

    [Fact]
    public void Side_margins_grow_with_height()
    {
        LivePack p = Pack();
        EdgeMargin side = p.Edges.Single(e => e.EdgeId == "e2");
        Assert.Equal(4.0, LiveEngine.MarginAt(side, 20.0, p.Height)!.Value, 3);
        Assert.Equal(3.0, LiveEngine.MarginAt(p.Edges.Single(e => e.EdgeId == "e1"), 20.0, p.Height)!.Value, 3);
        // At 20 m even the moved building is too close to its sides (needs 4 m, has 3.15).
        LiveStatus s = LiveEngine.Evaluate(p, Snapshot(dx: -0.35, dy: 0.6, height: 20.0));
        Assert.Contains(s.Setbacks, x => x.EdgeId == "e2" && x.RequiredM == 4.0);
    }

    [Fact]
    public void Distance_is_zero_when_an_outline_crosses_the_plot_line()
    {
        var square = new List<Pt> { new(-1, -1), new(1, -1), new(1, 1), new(-1, 1) };
        Assert.Equal(0, LiveEngine.DistanceToSegment(square, new Pt(-5, 0), new Pt(5, 0)));
        Assert.Equal(2, LiveEngine.DistanceToSegment(square, new Pt(-5, 3), new Pt(5, 3)), 6);
    }
}
