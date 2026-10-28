using ComplianceChecker.Core.Api;
using ComplianceChecker.Core.Model;

namespace ComplianceChecker.Core.Live;

/// <summary>A closed polyline of a 2D drawing, in drawing units, as the AutoCAD plug-in reads it.</summary>
public sealed record DrawingPolyline(string Handle, string Layer, IReadOnlyList<Pt> Points);

/// <summary>
/// AutoCAD live mode: the open drawing's polylines → a <see cref="LiveSnapshot"/> in plot
/// coordinates, using the server's floor frames (which floor plan a polyline is on, and how that
/// plan was moved onto the plot). Footprints on the site plan are already in plot coordinates.
///
/// FSI is measured as a change: the built-up area drawn now, minus the same at the last check, added
/// to the server's built-up figure. So the preview matches the report right after a check, and moves
/// with every edit, whatever the server deducts. Built-up area on a floor plan is the union of the FSI
/// outlines and the rooms: a room drawn past the FSI outline is new area at once, and a room inside it
/// isn't counted twice. Rooms and FSI outlines both count as the building for the setbacks.
/// </summary>
public sealed class DrawingLive
{
    private static readonly string[] FsiRoles = ["fsi_resi", "fsi_comm", "fsi_other"];
    private readonly DrawingFrames _frames;
    private readonly Dictionary<string, string> _roles;
    private readonly IReadOnlyDictionary<string, string> _names;
    private double? _baseFsiM2;

    public DrawingLive(DrawingFrames frames, IReadOnlyDictionary<string, string>? names = null)
    {
        _frames = frames;
        _roles = new Dictionary<string, string>(frames.Roles, StringComparer.OrdinalIgnoreCase);
        _names = names ?? new Dictionary<string, string>();
    }

    public string? RoleOf(string layer) => _roles.TryGetValue(layer, out string? r) ? r : null;

    /// <summary>Only rooms, footprints and FSI polylines matter to the live checks.</summary>
    public bool Watches(string layer) =>
        RoleOf(layer) is "room" or "footprint" or "fsi_resi" or "fsi_comm" or "fsi_other";

    /// <summary>Drawn on a floor plan (moved onto the plot by the plan's frame), not on the site plan.</summary>
    public bool OnFloorPlan(string layer) => RoleOf(layer) is "room" or "fsi_resi" or "fsi_comm" or "fsi_other";

    /// <summary>Remember the FSI area as it was at the check (call once, right after it).</summary>
    public void SetBaseline(IEnumerable<DrawingPolyline> polylines) => _baseFsiM2 = FsiArea(polylines);

    public LiveSnapshot Snapshot(IEnumerable<DrawingPolyline> polylines, double? checkedUsedM2)
    {
        var list = polylines.ToList();
        var snap = new LiveSnapshot();
        double s = _frames.Scale;
        foreach (DrawingPolyline p in list)
        {
            if (p.Points.Count < 3)
                continue;
            string? role = RoleOf(p.Layer);
            if (role == "footprint")
                snap.Outlines.Add(new LiveOutline(p.Handle, "building outline", p.Points.Select(q => new Pt(q.X * s, q.Y * s)).ToList()));
            else if (OnFloorPlan(p.Layer) && FloorOf(p.Points[0]) is { } f)
                snap.Outlines.Add(new LiveOutline(p.Handle,
                    _names.TryGetValue(p.Handle, out string? n) ? n : role == "room" ? "room" : "built-up area",
                    p.Points.Select(q => ToModel(q, f)).ToList()));
        }
        if (checkedUsedM2 is double used && _baseFsiM2 is double before && FsiArea(list) is double now)
            snap.BuiltUpM2 = Math.Round(used + (now - before), 2);
        return snap;
    }

    /// <summary>A plot-coordinate point (metres) drawn on a floor plan, in drawing units.</summary>
    public Pt ToDrawing(Pt model, FloorFrame f) =>
        new((model.X - f.Shift[0]) / _frames.Scale, (model.Y - f.Shift[1]) / _frames.Scale);

    public Pt ToModel(Pt drawing, FloorFrame f) =>
        new(drawing.X * _frames.Scale + f.Shift[0], drawing.Y * _frames.Scale + f.Shift[1]);

    public IReadOnlyList<FloorFrame> Floors => _frames.Floors;

    public double Scale => _frames.Scale;

    public FloorFrame? FloorOf(Pt p) =>
        _frames.Floors.FirstOrDefault(f => f.Bounds[0] <= p.X && p.X <= f.Bounds[2] && f.Bounds[1] <= p.Y && p.Y <= f.Bounds[3]);

    /// <summary>
    /// Built-up area (m²): per floor plan, the union of its FSI outlines and rooms, counted once per floor
    /// the plan stands for. Exact along scanlines every 5 cm.
    /// </summary>
    private double? FsiArea(IEnumerable<DrawingPolyline> polylines)
    {
        double total = 0;
        bool any = false;
        var byFloor = polylines
            .Where(p => p.Points.Count >= 3 && OnFloorPlan(p.Layer))
            .Select(p => (p.Points, Floor: FloorOf(p.Points[0])))
            .Where(x => x.Floor is not null)
            .GroupBy(x => x.Floor!);
        foreach (var floor in byFloor)
        {
            var polys = floor.Select(x => x.Points).ToList();
            total += UnionArea(polys, 0.05 / _frames.Scale) * _frames.Scale * _frames.Scale * Math.Max(1, floor.Key.Nums.Count);
            any = true;
        }
        return any ? total : null;
    }

    /// <summary>Area covered by any of the polygons (drawing units²): exact spans on scanlines <paramref name="step"/> apart.</summary>
    public static double UnionArea(IReadOnlyList<IReadOnlyList<Pt>> polys, double step)
    {
        double y0 = polys.Min(p => p.Min(q => q.Y)), y1 = polys.Max(p => p.Max(q => q.Y));
        double area = 0;
        var spans = new List<(double A, double B)>();
        var xs = new List<double>();
        for (double y = y0 + step / 2; y < y1; y += step)
        {
            spans.Clear();
            foreach (IReadOnlyList<Pt> poly in polys)
            {
                xs.Clear();
                for (int i = 0; i < poly.Count; i++)
                {
                    Pt a = poly[i], b = poly[(i + 1) % poly.Count];
                    if ((a.Y <= y) != (b.Y <= y))
                        xs.Add(a.X + (y - a.Y) / (b.Y - a.Y) * (b.X - a.X));
                }
                xs.Sort();
                for (int i = 0; i + 1 < xs.Count; i += 2)
                    spans.Add((xs[i], xs[i + 1]));
            }
            spans.Sort();
            double end = double.MinValue;
            foreach (var (a, b) in spans)
            {
                if (b <= end)
                    continue;
                area += (b - Math.Max(a, end)) * step;
                end = b;
            }
        }
        return area;
    }

    public static double Area(IReadOnlyList<Pt> p)
    {
        double a = 0;
        for (int i = 0; i < p.Count; i++)
        {
            Pt q = p[i], r = p[(i + 1) % p.Count];
            a += q.X * r.Y - r.X * q.Y;
        }
        return a / 2;
    }
}
