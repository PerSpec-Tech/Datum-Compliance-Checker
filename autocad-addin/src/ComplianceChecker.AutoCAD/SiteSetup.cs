using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Threading.Tasks;
using Autodesk.AutoCAD.ApplicationServices;
using Autodesk.AutoCAD.DatabaseServices;
using Autodesk.AutoCAD.EditorInput;
using Autodesk.AutoCAD.Geometry;
using Autodesk.AutoCAD.GraphicsInterface;
using ComplianceChecker.Core.Api;
using AcApp = Autodesk.AutoCAD.ApplicationServices.Application;
using Polyline = Autodesk.AutoCAD.DatabaseServices.Polyline;

namespace ComplianceChecker.AutoCAD
{
    /// <summary>What the site dialog edits; kept across the dialog's trips to the drawing (picks).</summary>
    internal sealed class SiteState
    {
        public double? Lat { get; set; }
        public double? Lon { get; set; }
        public string? LocationNote { get; set; }
        public bool LocationChanged { get; set; }
        /// <summary>North from AutoCAD's geographic location, as the web map's rotation (degrees), and
        /// the drawing point (metres) that sits at Lat/Lon.</summary>
        public double? RotationDeg { get; set; }
        public double[]? Anchor { get; set; }
        public (double Lat, double Lon)? AnchorAt { get; set; }

        /// <summary>A plot picked in the drawing (drawing units); null = the drawing's own plot.</summary>
        public List<Point2d>? PickedPlot { get; set; }
        public List<SideInfo> Sides { get; set; } = new();
        public Dictionary<string, (string Kind, double? Width)> Tags { get; } = new();
        public Dictionary<string, object?> Facts { get; } = new();

        public string PlotNote { get; set; } = "";
    }

    internal enum SiteAction { Cancel, Save, PickPlot, PickRoad, Browser }

    /// <summary>
    /// CCSITE inside AutoCAD (P11.2): location (AutoCAD's own geographic location, an address search
    /// or coordinates), the plot (from the drawing, or picked), what each side faces (picked on the
    /// drawing) and the planning facts. Saved as declared brief answers, then the check runs.
    /// </summary>
    internal static class SiteSetup
    {
        private static readonly List<Entity> Labels = new();

        public static async Task RunAsync(Document doc, ApiClient api)
        {
            Editor ed = doc.Editor;
            ed.WriteMessage("\nCompliance: reading the drawing for the site…");
            string pid = await Checker.SendAsync(doc, api);
            Markup markup = Markup.FromModelJson(await api.GetModelJsonAsync(pid), doc.Database);
            double scale = Markup.MetresPerUnit(doc.Database);

            var state = new SiteState { Sides = markup.Sides.ToList() };
            foreach (SideInfo s in markup.Sides.Where(s => s.Kind is not null))
                state.Tags[s.Id] = (s.Kind!, s.RoadWidthM);
            state.PlotNote = markup.HasPlot ? $"From the drawing: {Describe(markup.Sides, scale)}" : "No plot boundary in the drawing yet.";
            if (markup.Location is { } loc)
                (state.Lat, state.Lon, state.LocationNote) = (loc.Lat, loc.Lon, "from the project");
            if (GeoLocation(doc.Database, Centre(markup.Sides)) is { } geo)
            {
                if (state.Lat is null)
                    (state.Lat, state.Lon, state.LocationNote, state.LocationChanged) = (geo.Lat, geo.Lon, "from AutoCAD's geographic location", true);
                Point2d c = Centre(markup.Sides);
                (state.RotationDeg, state.Anchor, state.AnchorAt) = (geo.RotationDeg, new[] { Math.Round(c.X * scale, 3), Math.Round(c.Y * scale, 3) }, (geo.Lat, geo.Lon));
                if (geo.RotationDeg is { } r)
                    Log.Info($"north from GEOGRAPHICLOCATION: {r:0.##}°");
            }

            try
            {
                while (true)
                {
                    ShowSideLabels(state.Sides, doc.Database);
                    var window = new SiteWindow(api, pid, state);
                    AcApp.ShowModalWindow(window);
                    switch (window.Action)
                    {
                        // Prompts on the drawing need a command context (we're past an await here).
                        case SiteAction.PickPlot:
                            await AcApp.DocumentManager.ExecuteInCommandContextAsync(_ =>
                            {
                                PickPlot(ed, state, scale);
                                return Task.CompletedTask;
                            }, null);
                            continue;
                        case SiteAction.PickRoad:
                            await AcApp.DocumentManager.ExecuteInCommandContextAsync(_ =>
                            {
                                PickRoad(ed, state);
                                return Task.CompletedTask;
                            }, null);
                            continue;
                        case SiteAction.Browser:
                            Checker.OpenInBrowser($"/w/{Uri.EscapeDataString(pid)}?site=1");
                            return;
                        case SiteAction.Save:
                            await api.PatchBriefAsync(pid, Answers(state, scale));
                            Log.Info($"site saved for {pid}");
                            ClearLabels();
                            await Checker.CheckAsync(doc);
                            return;
                        default:
                            return;
                    }
                }
            }
            finally
            {
                ClearLabels();
            }
        }

        private static Dictionary<string, object?> Answers(SiteState s, double scale)
        {
            var answers = new Dictionary<string, object?>(s.Facts);
            if (s.LocationChanged && s.Lat is { } lat && s.Lon is { } lon)
                answers["project.location"] = new { lat, lon };
            // The drawing's own north places it on the web map without turning it by hand.
            // (Only while the location is AutoCAD's own: an address searched here moves the building.)
            if (s.RotationDeg is { } rot && s.Anchor is { } anchor && s.AnchorAt is { } at
                && s.Lat is { } plat && s.Lon is { } plon && Math.Abs(plat - at.Lat) < 1e-4 && Math.Abs(plon - at.Lon) < 1e-4)
                answers["site.placement"] = new { lat = at.Lat, lon = at.Lon, rotation_deg = rot, anchor };
            if (s.PickedPlot is { } plot)
                answers["site.boundary"] = plot.Select(p => new[] { Math.Round(p.X * scale, 3), Math.Round(p.Y * scale, 3) }).ToList();
            var edges = s.Tags.ToDictionary(
                kv => kv.Key,
                kv => (object)(kv.Value.Kind == "road"
                    ? new Dictionary<string, object?> { ["kind"] = "road", ["road_width_m"] = kv.Value.Width }
                    : new Dictionary<string, object?> { ["kind"] = kv.Value.Kind }));
            if (edges.Count > 0)
                answers["site.edges"] = edges;
            return answers;
        }

        // ------------------------------------------------------------------ picks on the drawing

        private static void PickPlot(Editor ed, SiteState s, double scale)
        {
            var opt = new PromptEntityOptions("\nSelect the plot boundary (a closed polyline): ");
            opt.SetRejectMessage("\nThat isn't a polyline.");
            opt.AddAllowedClass(typeof(Polyline), true);
            PromptEntityResult r = ed.GetEntity(opt);
            if (r.Status != PromptStatus.OK)
                return;
            using Transaction tr = ed.Document.Database.TransactionManager.StartOpenCloseTransaction();
            var pl = (Polyline)tr.GetObject(r.ObjectId, OpenMode.ForRead);
            var pts = Enumerable.Range(0, pl.NumberOfVertices).Select(pl.GetPoint2dAt).ToList();
            if (pts.Count < 3)
            {
                ed.WriteMessage("\nCompliance: a plot needs at least 3 corners.");
                return;
            }
            if (SignedArea(pts) < 0)
                pts.Reverse(); // counter-clockwise, like the server's plots
            s.PickedPlot = pts;
            s.Sides = pts.Select((p, i) => new SideInfo($"e{i + 1}", p, pts[(i + 1) % pts.Count], null, null)).ToList();
            s.Tags.Clear();
            s.PlotNote = $"Picked in the drawing: {Describe(s.Sides, scale)}";
        }

        private static void PickRoad(Editor ed, SiteState s)
        {
            if (s.Sides.Count == 0)
            {
                ed.WriteMessage("\nCompliance: set the plot first.");
                return;
            }
            PromptPointResult p = ed.GetPoint("\nClick on the plot side that faces a road: ");
            if (p.Status != PromptStatus.OK)
                return;
            var at = new Point2d(p.Value.X, p.Value.Y);
            SideInfo side = s.Sides.OrderBy(x => Distance(at, x.A, x.B)).First();
            var w = new PromptDoubleOptions($"\nRoad width at side {side.Id} in metres (DP width): ")
            {
                AllowNegative = false,
                AllowZero = false,
                DefaultValue = s.Tags.TryGetValue(side.Id, out var t) && t.Width is { } old ? old : 9.0,
                UseDefaultValue = true,
            };
            PromptDoubleResult width = ed.GetDouble(w);
            if (width.Status != PromptStatus.OK)
                return;
            s.Tags[side.Id] = ("road", width.Value);
            // the other sides become neighbours unless already said otherwise
            foreach (SideInfo other in s.Sides.Where(x => x.Id != side.Id && !s.Tags.ContainsKey(x.Id)))
                s.Tags[other.Id] = ("neighbour", null);
        }

        // ------------------------------------------------------------------ side labels while the dialog is open

        private static void ShowSideLabels(List<SideInfo> sides, Database db)
        {
            ClearLabels();
            if (sides.Count == 0)
                return;
            double unit = 1 / Markup.MetresPerUnit(db);
            foreach (SideInfo s in sides)
            {
                var line = new Line(new Point3d(s.A.X, s.A.Y, 0), new Point3d(s.B.X, s.B.Y, 0)) { ColorIndex = 4, LineWeight = LineWeight.LineWeight080 };
                var mid = new Point3d((s.A.X + s.B.X) / 2, (s.A.Y + s.B.Y) / 2, 0);
                var text = new DBText { TextString = s.Id, Position = mid, Height = 0.8 * unit, ColorIndex = 4 };
                foreach (Entity e in new Entity[] { line, text })
                {
                    TransientManager.CurrentTransientManager.AddTransient(e, TransientDrawingMode.DirectTopmost, 128, new IntegerCollection());
                    Labels.Add(e);
                }
            }
        }

        private static void ClearLabels()
        {
            foreach (Entity e in Labels)
            {
                TransientManager.CurrentTransientManager.EraseTransient(e, new IntegerCollection());
                e.Dispose();
            }
            Labels.Clear();
        }

        // ------------------------------------------------------------------ helpers

        /// <summary>AutoCAD's own geographic location (GEOGRAPHICLOCATION), at a point of the drawing,
        /// and north as the web map's rotation: the drawing's north vector (sin t, cos t) gives t.</summary>
        private static (double Lat, double Lon, double? RotationDeg)? GeoLocation(Database db, Point2d at)
        {
            try
            {
                if (db.GeoDataObject.IsNull)
                    return null;
                using Transaction tr = db.TransactionManager.StartOpenCloseTransaction();
                var geo = (GeoLocationData)tr.GetObject(db.GeoDataObject, OpenMode.ForRead);
                Point3d lonLat = geo.TransformToLonLatAlt(new Point3d(at.X, at.Y, 0));
                Vector2d n = geo.NorthDirectionVector;
                double? rot = n.Length > 1e-9 ? Math.Round(Math.Atan2(n.X, n.Y) * 180 / Math.PI, 2) : null;
                return (lonLat.Y, lonLat.X, rot);
            }
            catch (System.Exception e)
            {
                Log.Info("no geographic location: " + e.Message);
                return null;
            }
        }

        private static Point2d Centre(List<SideInfo> sides) =>
            sides.Count == 0 ? Point2d.Origin : new Point2d(sides.Average(s => s.A.X), sides.Average(s => s.A.Y));

        private static string Describe(List<SideInfo> sides, double scale)
        {
            var pts = sides.Select(s => s.A).ToList();
            double area = Math.Abs(SignedArea(pts)) * scale * scale;
            return string.Create(CultureInfo.InvariantCulture, $"{sides.Count} sides, {area:0} m²");
        }

        private static double SignedArea(List<Point2d> p) =>
            0.5 * p.Select((a, i) => a.X * p[(i + 1) % p.Count].Y - p[(i + 1) % p.Count].X * a.Y).Sum();

        private static double Distance(Point2d p, Point2d a, Point2d b)
        {
            Vector2d ab = b - a;
            double t = Math.Clamp((p - a).DotProduct(ab) / Math.Max(ab.DotProduct(ab), 1e-12), 0, 1);
            return p.GetDistanceTo(a + ab * t);
        }
    }
}
