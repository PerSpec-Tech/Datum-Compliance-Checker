using System.Globalization;

namespace ComplianceChecker.Core.Model;

/// <summary>Small 2D helpers. Polygons are lists of points, closed implicitly.</summary>
public static class Geometry
{
    public const double Tolerance = 0.01; // 1 cm

    /// <summary>Signed shoelace area: positive when counter-clockwise.</summary>
    public static double SignedArea(IReadOnlyList<Pt> poly)
    {
        double a = 0;
        for (int i = 0; i < poly.Count; i++)
        {
            Pt p = poly[i], q = poly[(i + 1) % poly.Count];
            a += p.X * q.Y - q.X * p.Y;
        }
        return a / 2;
    }

    public static double Area(IReadOnlyList<Pt> poly) => Math.Abs(SignedArea(poly));

    /// <summary>Counter-clockwise copy with duplicate closing point and near-duplicates removed.</summary>
    public static List<Pt> Normalise(IEnumerable<Pt> points)
    {
        var pts = new List<Pt>();
        foreach (Pt p in points)
            if (pts.Count == 0 || Dist(pts[^1], p) > Tolerance)
                pts.Add(p);
        if (pts.Count > 1 && Dist(pts[0], pts[^1]) <= Tolerance)
            pts.RemoveAt(pts.Count - 1);
        if (pts.Count >= 3 && SignedArea(pts) < 0)
            pts.Reverse();
        return pts;
    }

    public static double Dist(Pt a, Pt b) => Math.Sqrt((a.X - b.X) * (a.X - b.X) + (a.Y - b.Y) * (a.Y - b.Y));

    /// <summary>
    /// Chain unordered segments into one closed loop (property lines are often drawn as separate
    /// lines in any direction). Returns null if they don't form a single closed loop.
    /// </summary>
    public static List<Pt>? ChainLoop(IReadOnlyList<(Pt A, Pt B)> segments, double tol = 0.05)
    {
        if (segments.Count < 3)
            return null;
        var left = segments.ToList();
        var (start, next) = left[0];
        left.RemoveAt(0);
        var loop = new List<Pt> { start, next };
        while (left.Count > 0)
        {
            int i = left.FindIndex(s => Dist(s.A, next) <= tol || Dist(s.B, next) <= tol);
            if (i < 0)
                return null; // gap: not a single loop
            var s = left[i];
            left.RemoveAt(i);
            next = Dist(s.A, next) <= tol ? s.B : s.A;
            loop.Add(next);
        }
        if (Dist(loop[0], loop[^1]) > tol)
            return null; // not closed
        var result = Normalise(loop);
        return result.Count >= 3 ? result : null;
    }

    /// <summary>Stable key for a plot edge (rounded midpoint), used to remember site tags across exports.</summary>
    public static string EdgeKey(Pt a, Pt b)
    {
        double mx = Math.Round((a.X + b.X) / 2, 1), my = Math.Round((a.Y + b.Y) / 2, 1);
        return string.Create(CultureInfo.InvariantCulture, $"{mx:0.0},{my:0.0}");
    }

    public static List<List<double>> ToJson(IEnumerable<Pt> poly) =>
        poly.Select(p => new List<double> { Math.Round(p.X, 4), Math.Round(p.Y, 4) }).ToList();
}
