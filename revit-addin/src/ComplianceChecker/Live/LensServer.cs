using System;
using System.Collections.Generic;
using System.Linq;
using Autodesk.Revit.DB;
using Autodesk.Revit.DB.DirectContext3D;
using Autodesk.Revit.DB.ExternalService;
using ComplianceChecker.Core.Live;
using ComplianceChecker.Core.Model;

namespace ComplianceChecker.Live
{
    /// <summary>
    /// The compliance lens: transient graphics drawn by Revit's DirectContext3D over 3D and
    /// plan views. Never part of the model and never in the undo history. Draws:
    /// - the buildable line (the plot inset by each side's margin) in grey;
    /// - every element that crosses it, outlined in red (thin when it's under 10 cm in, P9 calm rules),
    ///   and the part of it past the line as a red hatched volume, from its bottom to its top;
    /// - the height limit as a hatched plane over the buildable area, red once the building goes through it.
    /// </summary>
    internal sealed class LensServer : IDirectContext3DServer
    {
        private static readonly Guid Id = new("6b3f2a91-8c4d-4e7a-b1f0-2d9c5e8a7f13");
        private readonly object _lock = new();
        private List<(XYZ A, XYZ B, ColorWithTransparency C)> _lines = new();
        private Outline? _bounds;
        private string? _docKey;

        public bool Enabled { get; set; }

        public void Update(string docKey, LivePack pack, LiveSnapshot snap, LiveStatus status, double groundFeet)
        {
            var lines = new List<(XYZ, XYZ, ColorWithTransparency)>();
            double z = groundFeet + Ft(0.02);
            var grey = new ColorWithTransparency(200, 200, 205, 0);
            var red = new ColorWithTransparency(245, 69, 92, 0);
            var pale = new ColorWithTransparency(250, 160, 170, 0);

            var dark = new ColorWithTransparency(120, 120, 128, 0);
            List<Pt>? area = pack.Envelope is { Count: >= 3 } env ? env.Select(p => new Pt(p[0], p[1])).ToList() : null;
            if (area is not null)
            {
                Ring(area, z, grey, lines);
                Ring(area, z + Ft(0.03), dark, lines);
            }

            // The height limit: a hatched plane over the buildable area (or the plot), posts at its corners.
            if (pack.Height.LimitM is double limit)
            {
                List<Pt> roof = area ?? pack.Edges.Select(e => new Pt(e.A[0], e.A[1])).ToList();
                var c = status.HeightOver ? red : new ColorWithTransparency(150, 150, 160, 0);
                double zl = groundFeet + Ft(limit);
                Ring(roof, zl, c, lines);
                foreach (var (a, b) in Hatch(roof, 1.5))
                    lines.Add((new XYZ(Ft(a.X), Ft(a.Y), zl), new XYZ(Ft(b.X), Ft(b.Y), zl), c));
                foreach (Pt p in roof)
                    lines.Add((new XYZ(Ft(p.X), Ft(p.Y), z), new XYZ(Ft(p.X), Ft(p.Y), zl), grey));
            }

            // The part of each element past the buildable line, as a red hatched volume.
            foreach (LiveOutline o in snap.Outlines.Where(o => status.Setbacks.Any(s => s.ElementId == o.ElementId && !s.Slight)))
            {
                double z0 = groundFeet + Ft(o.BottomM ?? 0), z1 = groundFeet + Ft(o.TopM ?? status.HeightM ?? 3);
                foreach (List<Pt> piece in LiveEngine.Encroachments(pack, status, o))
                {
                    Ring(piece, z0, red, lines);
                    Ring(piece, z1, red, lines);
                    foreach (Pt p in piece)
                        lines.Add((new XYZ(Ft(p.X), Ft(p.Y), z0), new XYZ(Ft(p.X), Ft(p.Y), z1), red));
                    foreach (var (a, b) in Hatch(piece, 0.25))
                    {
                        lines.Add((new XYZ(Ft(a.X), Ft(a.Y), z1), new XYZ(Ft(b.X), Ft(b.Y), z1), red));
                        lines.Add((new XYZ(Ft(a.X), Ft(a.Y), z0 + Ft(0.02)), new XYZ(Ft(b.X), Ft(b.Y), z0 + Ft(0.02)), red));
                    }
                }
            }
            var bad = status.Setbacks.GroupBy(s => s.ElementId).ToDictionary(g => g.Key, g => g.All(s => s.Slight));
            foreach (LiveOutline o in snap.Outlines.Where(o => bad.ContainsKey(o.ElementId)))
            {
                Ring(o.Points, z + Ft(0.01), bad[o.ElementId] ? pale : red, lines);
                if (!bad[o.ElementId])
                    Ring(o.Points, z + Ft(0.04), red, lines); // a second ring reads as a heavier line
            }

            var all = lines.SelectMany(l => new[] { l.Item1, l.Item2 }).ToList();
            lock (_lock)
            {
                _lines = lines;
                _docKey = docKey;
                _bounds = all.Count == 0
                    ? null
                    : new Outline(new XYZ(all.Min(p => p.X), all.Min(p => p.Y), all.Min(p => p.Z) - 1),
                                  new XYZ(all.Max(p => p.X), all.Max(p => p.Y), all.Max(p => p.Z) + 1));
            }
        }

        public void Clear()
        {
            lock (_lock)
            {
                _lines = new();
                _bounds = null;
            }
        }

        public static LensServer Register(LensServer lens)
        {
            if (ExternalServiceRegistry.GetService(ExternalServices.BuiltInExternalServices.DirectContext3DService)
                is MultiServerService service)
            {
                service.AddServer(lens);
                IList<Guid> active = service.GetActiveServerIds();
                active.Add(lens.GetServerId());
                service.SetActiveServers(active);
            }
            return lens;
        }

        // ------------------------------------------------------------------ IDirectContext3DServer

        public Guid GetServerId() => Id;
        public string GetVendorId() => "PERSPEC";
        public ExternalServiceId GetServiceId() => ExternalServices.BuiltInExternalServices.DirectContext3DService;
        public string GetName() => "Compliance lens";
        public string GetDescription() => "Buildable line and setback issues from Datum's live pack.";
        public string GetApplicationId() => "";
        public string GetSourceId() => "";
        public bool UsesHandles() => false;
        public bool UseInTransparentPass(View view) => false;

        public bool CanExecute(View view)
        {
            if (!Enabled || view is not (View3D or ViewPlan))
                return false;
            lock (_lock)
                return _lines.Count > 0 && _docKey == LiveController.Key(view.Document);
        }

        public Outline GetBoundingBox(View view)
        {
            lock (_lock)
                return _bounds ?? new Outline(XYZ.Zero, XYZ.Zero);
        }

        public void RenderScene(View view, DisplayStyle displayStyle)
        {
            List<(XYZ A, XYZ B, ColorWithTransparency C)> lines;
            lock (_lock)
                lines = _lines;
            if (lines.Count == 0 || DrawContext.IsTransparentPass())
                return;

            int vertices = lines.Count * 2;
            var vb = new VertexBuffer(vertices * VertexPositionColored.GetSizeInFloats());
            vb.Map(vertices * VertexPositionColored.GetSizeInFloats());
            VertexStreamPositionColored vs = vb.GetVertexStreamPositionColored();
            foreach (var (a, b, c) in lines)
            {
                vs.AddVertex(new VertexPositionColored(a, c));
                vs.AddVertex(new VertexPositionColored(b, c));
            }
            vb.Unmap();

            var ib = new IndexBuffer(lines.Count * IndexLine.GetSizeInShortInts());
            ib.Map(lines.Count * IndexLine.GetSizeInShortInts());
            IndexStreamLine ls = ib.GetIndexStreamLine();
            for (int i = 0; i < lines.Count; i++)
                ls.AddLine(new IndexLine(2 * i, 2 * i + 1));
            ib.Unmap();

            var format = new VertexFormat(VertexFormatBits.PositionColored);
            var effect = new EffectInstance(VertexFormatBits.PositionColored);
            DrawContext.FlushBuffer(vb, vertices, ib, lines.Count * IndexLine.GetSizeInShortInts(),
                format, effect, PrimitiveType.LineList, 0, lines.Count);
        }

        // ------------------------------------------------------------------ helpers

        private static void Ring(IReadOnlyList<Pt> pts, double z, ColorWithTransparency c, List<(XYZ, XYZ, ColorWithTransparency)> into)
        {
            for (int i = 0; i < pts.Count; i++)
            {
                Pt a = pts[i], b = pts[(i + 1) % pts.Count];
                if (pts.Count == 2 && i == 1)
                    break;
                into.Add((new XYZ(Ft(a.X), Ft(a.Y), z), new XYZ(Ft(b.X), Ft(b.Y), z), c));
            }
        }

        /// <summary>45° hatch lines inside a polygon, every <paramref name="spacing"/> metres (even-odd scanlines).</summary>
        private static List<(Pt, Pt)> Hatch(IReadOnlyList<Pt> poly, double spacing)
        {
            // Rotate so the hatch runs along x, scan in y, rotate the segments back.
            const double k = 0.70710678118654752;
            Pt Rot(Pt p) => new(k * (p.X + p.Y), k * (p.Y - p.X));
            Pt Back(Pt p) => new(k * (p.X - p.Y), k * (p.X + p.Y));
            var r = poly.Select(Rot).ToList();
            var segments = new List<(Pt, Pt)>();
            double y0 = r.Min(p => p.Y), y1 = r.Max(p => p.Y);
            for (double y = Math.Ceiling(y0 / spacing) * spacing; y < y1 && segments.Count < 4000; y += spacing)
            {
                var xs = new List<double>();
                for (int i = 0; i < r.Count; i++)
                {
                    Pt a = r[i], b = r[(i + 1) % r.Count];
                    if ((a.Y <= y) != (b.Y <= y))
                        xs.Add(a.X + (y - a.Y) / (b.Y - a.Y) * (b.X - a.X));
                }
                xs.Sort();
                for (int i = 0; i + 1 < xs.Count; i += 2)
                    segments.Add((Back(new Pt(xs[i], y)), Back(new Pt(xs[i + 1], y))));
            }
            return segments;
        }

        private static double Ft(double metres) => UnitUtils.ConvertToInternalUnits(metres, UnitTypeId.Meters);
    }
}
