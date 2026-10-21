using ComplianceChecker.Core.Model;

namespace ComplianceChecker.Core.Live;

/// <summary>What the add-in measured just now, in the same metres and plan coordinates as the export.</summary>
public sealed class LiveSnapshot
{
    /// <summary>Building elements seen from above (walls, floors, columns…), one outline each.</summary>
    public List<LiveOutline> Outlines { get; } = new();
    public double? HeightM { get; set; }
    public double? BuiltUpM2 { get; set; }
    /// <summary>source_id (Revit UniqueId) → measured field (clear_height_m, width_m…) → value.</summary>
    public Dictionary<string, Dictionary<string, double?>> Values { get; } = new();
}

public sealed record LiveOutline(string ElementId, string Label, List<Pt> Points);

public sealed record SetbackIssue(
    string ElementId, string Label, string EdgeId, string? EdgeKind, double DistanceM, double RequiredM,
    string? RuleId, string? ClauseRef)
{
    public double DeficitM => Math.Round(RequiredM - DistanceM, 3);
    /// <summary>Under 10 cm in: a thin outline, not a red band (calm by design, P9).</summary>
    public bool Slight => DeficitM < 0.10;
}

public sealed record ThresholdIssue(
    string SourceId, string ElementId, string RuleId, string Title, string ClauseRef, string Field,
    string Op, double Value, double Limit)
{
    public double FixBy => Math.Round(Math.Abs(Limit - Value), 3);
}

public sealed record LiveStatus(
    double? FsiUsedM2, double? FsiMaxM2, double? FsiBaseM2, double? FsiLeftM2, double? Fsi, double? FsiMax,
    double? HeightM, IReadOnlyList<SetbackIssue> Setbacks, IReadOnlyList<ThresholdIssue> Thresholds,
    IReadOnlyDictionary<string, double?> MarginsNow)
{
    public int IssueCount => Setbacks.Select(s => s.ElementId).Distinct().Count() + Thresholds.Count;

    /// <summary>The one-line strip: "FSI 2.31 / 2.50 · 186 m² left · height 14.2 m · margins ✓ · 2 elements ✕".</summary>
    public string StripText()
    {
        var parts = new List<string>();
        if (Fsi is double f && FsiMax is double fm)
        {
            string left = FsiLeftM2 is double l ? (l >= 0 ? $"{l:0} m² left" : $"{-l:0} m² over") : "";
            parts.Add($"FSI {f:0.00} / {fm:0.00}{(left.Length > 0 ? " · " + left : "")}");
        }
        if (HeightM is double h)
            parts.Add($"height {h:0.0} m");
        int setbacks = Setbacks.Select(s => s.ElementId).Distinct().Count();
        parts.Add(setbacks == 0 ? "margins ✓" : $"margins ✕ {setbacks}");
        parts.Add(Thresholds.Count == 0 ? "sizes ✓" : $"sizes ✕ {Thresholds.Count}");
        return string.Join("  ·  ", parts);
    }
}

/// <summary>
/// Live preview (P9.2, D32): the live pack's limits against what the model has right now. Pure
/// geometry and comparisons, no network, milliseconds. The full check stays the official result.
/// </summary>
public static class LiveEngine
{
    public static LiveStatus Evaluate(LivePack pack, LiveSnapshot snap)
    {
        double? height = snap.HeightM ?? pack.Height.CurrentM;
        var margins = pack.Edges.ToDictionary(e => e.EdgeId, e => MarginAt(e, height, pack.Height));

        var setbacks = new List<SetbackIssue>();
        foreach (LiveOutline o in snap.Outlines)
        {
            if (o.Points.Count < 2)
                continue;
            foreach (EdgeMargin e in pack.Edges)
            {
                if (margins[e.EdgeId] is not double need)
                    continue;
                var a = new Pt(e.A[0], e.A[1]);
                var b = new Pt(e.B[0], e.B[1]);
                double d = DistanceToSegment(o.Points, a, b);
                if (d < need - 1e-6)
                    setbacks.Add(new SetbackIssue(o.ElementId, o.Label, e.EdgeId, e.Kind, Math.Round(d, 3), need, e.RuleId, e.ClauseRef));
            }
        }

        var thresholds = new List<ThresholdIssue>();
        foreach (Threshold t in pack.Thresholds)
        {
            for (int i = 0; i < t.SourceIds.Count; i++)
            {
                string? sid = t.SourceIds[i];
                if (sid is null || !snap.Values.TryGetValue(sid, out var fields) ||
                    !fields.TryGetValue(t.Field, out double? v) || v is not double value)
                    continue;
                if (!Holds(value, t.Op, t.Limit))
                    thresholds.Add(new ThresholdIssue(sid, t.ElementIds[i], t.RuleId, t.Title, t.ClauseRef, t.Field, t.Op, value, t.Limit));
            }
        }

        double? used = snap.BuiltUpM2 ?? pack.Fsi.UsedM2;
        double? plot = pack.Fsi.PlotAreaM2;
        return new LiveStatus(
            used, pack.Fsi.MaxBuiltUpM2, pack.Fsi.BaseBuiltUpM2,
            used is double u && pack.Fsi.MaxBuiltUpM2 is double max ? Math.Round(max - u, 1) : null,
            used is double u2 && plot is double p && p > 0 ? Math.Round(u2 / p, 3) : null,
            pack.Fsi.Max, height, setbacks, thresholds, margins);
    }

    /// <summary>The side's margin at a building height: the larger of the two samples around it.</summary>
    public static double? MarginAt(EdgeMargin e, double? heightM, HeightSamples h)
    {
        if (e.MarginByHeight.Count == 0 || heightM is not double hm)
            return e.MarginM;
        // Snap to a sample when the height sits on one (float noise), else take the larger neighbour.
        double i = Math.Clamp(Math.Round(hm / h.StepM, 6), 0, e.MarginByHeight.Count - 1);
        double? lo = e.MarginByHeight[(int)Math.Floor(i)];
        double? hi = e.MarginByHeight[(int)Math.Ceiling(i)];
        if (lo is null && hi is null)
            return e.MarginM;
        return Math.Max(lo ?? double.MinValue, hi ?? double.MinValue);
    }

    public static bool Holds(double value, string op, double limit) => op switch
    {
        ">=" => value >= limit - 1e-9,
        "<=" => value <= limit + 1e-9,
        ">" => value > limit,
        "<" => value < limit,
        _ => true,
    };

    /// <summary>Shortest distance from an outline (closed polygon or polyline) to segment a–b; 0 if they cross.</summary>
    public static double DistanceToSegment(IReadOnlyList<Pt> outline, Pt a, Pt b)
    {
        double best = double.MaxValue;
        int n = outline.Count;
        for (int i = 0; i < n; i++)
        {
            Pt p = outline[i], q = outline[(i + 1) % n];
            if (n == 2 && i == 1)
                break;
            best = Math.Min(best, SegmentDistance(p, q, a, b));
            if (best == 0)
                return 0;
        }
        return best;
    }

    private static double SegmentDistance(Pt p, Pt q, Pt a, Pt b)
    {
        if (Intersects(p, q, a, b))
            return 0;
        return Math.Min(Math.Min(PointSeg(p, a, b), PointSeg(q, a, b)), Math.Min(PointSeg(a, p, q), PointSeg(b, p, q)));
    }

    private static double PointSeg(Pt p, Pt a, Pt b)
    {
        double dx = b.X - a.X, dy = b.Y - a.Y;
        double len2 = dx * dx + dy * dy;
        double t = len2 == 0 ? 0 : Math.Clamp(((p.X - a.X) * dx + (p.Y - a.Y) * dy) / len2, 0, 1);
        double x = a.X + t * dx - p.X, y = a.Y + t * dy - p.Y;
        return Math.Sqrt(x * x + y * y);
    }

    private static bool Intersects(Pt p1, Pt p2, Pt p3, Pt p4)
    {
        double d1 = Cross(p3, p4, p1), d2 = Cross(p3, p4, p2), d3 = Cross(p1, p2, p3), d4 = Cross(p1, p2, p4);
        return ((d1 > 0 && d2 < 0) || (d1 < 0 && d2 > 0)) && ((d3 > 0 && d4 < 0) || (d3 < 0 && d4 > 0));
    }

    private static double Cross(Pt a, Pt b, Pt c) => (b.X - a.X) * (c.Y - a.Y) - (b.Y - a.Y) * (c.X - a.X);
}
