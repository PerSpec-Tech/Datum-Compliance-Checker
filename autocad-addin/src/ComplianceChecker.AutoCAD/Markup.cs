using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json;
using Autodesk.AutoCAD.DatabaseServices;
using Autodesk.AutoCAD.Geometry;

namespace ComplianceChecker.AutoCAD
{
    /// <summary>
    /// Where results are on the drawing, in drawing units: plot sides and the building outline come
    /// from the checked model (metres, read by the server from this drawing), scaled back with the
    /// drawing's $INSUNITS the same way the server read it. Plus the revision-cloud geometry.
    /// </summary>
    /// <summary>One plot side in drawing units, and what it faces (road / neighbour / open_space).</summary>
    internal sealed record SideInfo(string Id, Point2d A, Point2d B, string? Kind, double? RoadWidthM);

    internal sealed class Markup
    {
        private readonly Dictionary<string, (Point2d A, Point2d B)> _edges = new();
        private readonly List<Point2d> _footprint = new();

        public static Markup? Current { get; set; }

        /// <summary>The plot's sides as the check sees them (drawing units), with what each faces.</summary>
        public List<SideInfo> Sides { get; } = new();

        /// <summary>The project location in the model (from the brief or the drawing), if any.</summary>
        public (double Lat, double Lon)? Location { get; private set; }

        public bool HasPlot => Sides.Count > 0;

        public static Markup FromModelJson(string json, Database db)
        {
            double scale = MetresPerUnit(db);
            var m = new Markup();
            using var doc = JsonDocument.Parse(json);
            JsonElement model = doc.RootElement.GetProperty("model");
            Point2d P(JsonElement p) => new(p[0].GetDouble() / scale, p[1].GetDouble() / scale);
            static string? Str(JsonElement fact) =>
                fact.TryGetProperty("value", out var v) && v.ValueKind == JsonValueKind.String ? v.GetString() : null;
            static double? Num(JsonElement fact) =>
                fact.TryGetProperty("value", out var v) && v.ValueKind == JsonValueKind.Number ? v.GetDouble() : null;
            foreach (JsonElement e in model.GetProperty("site").GetProperty("edges").EnumerateArray())
            {
                string id = e.GetProperty("id").GetString()!;
                (Point2d a, Point2d b) = (P(e.GetProperty("a")), P(e.GetProperty("b")));
                m._edges[id] = (a, b);
                m.Sides.Add(new SideInfo(id, a, b, Str(e.GetProperty("kind")), Num(e.GetProperty("road_width_m"))));
            }
            if (model.GetProperty("building").GetProperty("footprint") is { ValueKind: JsonValueKind.Array } fp)
                m._footprint.AddRange(fp.EnumerateArray().Select(P));
            if (model.GetProperty("project").GetProperty("location").GetProperty("value") is { ValueKind: JsonValueKind.Object } loc)
                m.Location = (loc.GetProperty("lat").GetDouble(), loc.GetProperty("lon").GetDouble());
            return m;
        }

        /// <summary>Same table as the server's reader (adapters/dxf.py _UNITS).</summary>
        public static double MetresPerUnit(Database db) => db.Insunits switch
        {
            UnitsValue.Inches => 0.0254,
            UnitsValue.Feet => 0.3048,
            UnitsValue.Millimeters => 0.001,
            UnitsValue.Centimeters => 0.01,
            _ => 1.0,
        };

        /// <summary>A thin band along a plot side, so the cloud wraps the side.</summary>
        public List<Point2d>? Edge(string id, double halfWidth)
        {
            if (!_edges.TryGetValue(id, out var e))
                return null;
            Vector2d d = (e.B - e.A).GetNormal();
            Vector2d n = new(-d.Y * halfWidth, d.X * halfWidth);
            return new() { e.A - n, e.B - n, e.B + n, e.A + n };
        }

        public List<Point2d>? Footprint => _footprint.Count > 2 ? _footprint : null;

        /// <summary>
        /// A revision cloud around a box: arcs of about equal length bulging outward, as AutoCAD's
        /// REVCLOUD draws them. The polyline isn't added to the drawing; it is shown as a transient.
        /// </summary>
        public static Polyline Cloud(Extents2d box, double arc)
        {
            var corners = new[]
            {
                box.MinPoint, new Point2d(box.MaxPoint.X, box.MinPoint.Y),
                box.MaxPoint, new Point2d(box.MinPoint.X, box.MaxPoint.Y),
            };
            var pts = new List<Point2d>();
            for (int i = 0; i < 4; i++)
            {
                Point2d a = corners[i], b = corners[(i + 1) % 4];
                int n = Math.Max(1, (int)Math.Round(a.GetDistanceTo(b) / arc));
                for (int k = 0; k < n; k++)
                    pts.Add(a + (b - a) * ((double)k / n));
            }
            var pl = new Polyline(pts.Count);
            for (int i = 0; i < pts.Count; i++)
                pl.AddVertexAt(i, pts[i], 0.55, 0, 0); // counter-clockwise corners: positive bulge = outward
            pl.Closed = true;
            pl.ConstantWidth = arc * 0.07;
            return pl;
        }

        public static Extents2d Box(IEnumerable<Point2d> pts, double margin)
        {
            var list = pts.ToList();
            return new Extents2d(
                list.Min(p => p.X) - margin, list.Min(p => p.Y) - margin,
                list.Max(p => p.X) + margin, list.Max(p => p.Y) + margin);
        }
    }
}
