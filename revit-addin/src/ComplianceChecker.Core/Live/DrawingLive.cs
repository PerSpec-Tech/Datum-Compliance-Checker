using ComplianceChecker.Core.Api;
using ComplianceChecker.Core.Model;

namespace ComplianceChecker.Core.Live;

/// <summary>A closed polyline of a 2D drawing, in drawing units, as the AutoCAD plug-in reads it.</summary>
public sealed record DrawingPolyline(string Handle, string Layer, IReadOnlyList<Pt> Points);

/// <summary>
/// AutoCAD live mode (P11.4): the open drawing's polylines → a <see cref="LiveSnapshot"/> in plot
/// coordinates, using the server's floor frames (which floor plan a polyline is on, and how that
/// plan was moved onto the plot). Footprints on the site plan are already in plot coordinates.
///
/// FSI is measured as a change: the PreDCR FSI polylines' area now, minus their area at the last
/// check, added to the server's built-up figure. So the preview matches the report right after a
/// check, and moves with every edit, whatever the server deducts.
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
            else if (role == "room" && FloorOf(p.Points[0]) is { } f)
                snap.Outlines.Add(new LiveOutline(p.Handle, _names.TryGetValue(p.Handle, out string? n) ? n : "room",
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

    /// <summary>Built-up area on the FSI layers (m²), each floor plan counted once per floor it stands for.</summary>
    private double? FsiArea(IEnumerable<DrawingPolyline> polylines)
    {
        double total = 0;
        bool any = false;
        foreach (DrawingPolyline p in polylines)
        {
            if (p.Points.Count < 3 || !FsiRoles.Contains(RoleOf(p.Layer)) || FloorOf(p.Points[0]) is not { } f)
                continue;
            total += Math.Abs(Area(p.Points)) * _frames.Scale * _frames.Scale * Math.Max(1, f.Nums.Count);
            any = true;
        }
        return any ? total : null;
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
