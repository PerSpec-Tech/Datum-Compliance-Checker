using System;
using System.Collections.Generic;
using System.Linq;
using Autodesk.Revit.DB;
using Autodesk.Revit.DB.Architecture;
using ComplianceChecker.Core.Live;
using ComplianceChecker.Core.Model;
using ComplianceChecker.Export;
using RevitArea = Autodesk.Revit.DB.Area;
using Units = ComplianceChecker.Export.Units;

namespace ComplianceChecker.Live
{
    /// <summary>
    /// Reads what live mode needs from the open model, quickly and read-only (no transactions):
    /// plan outlines of building elements, building height, built-up area, and the fields the live
    /// pack's thresholds measure (keyed by UniqueId, the export's source_id). Same metres and plan
    /// coordinates as <see cref="RevitExporter"/>.
    /// </summary>
    internal static class LiveSnapshotReader
    {
        private static readonly BuiltInCategory[] Boxed =
        {
            BuiltInCategory.OST_Columns, BuiltInCategory.OST_StructuralColumns, BuiltInCategory.OST_GenericModel,
            BuiltInCategory.OST_Roofs, BuiltInCategory.OST_Stairs,
        };

        public static LiveSnapshot Read(Document doc)
        {
            var snap = new LiveSnapshot();
            var levels = new FilteredElementCollector(doc).OfClass(typeof(Level)).Cast<Level>().ToList();
            Level? ground = RevitExporter.GroundLevel(levels);
            double groundZ = ground?.ProjectElevation ?? 0;

            // Walls: a rectangle around straight walls, the tessellated centre line otherwise.
            foreach (Wall w in new FilteredElementCollector(doc).OfClass(typeof(Wall)).Cast<Wall>())
            {
                if (w.Location is not LocationCurve lc)
                    continue;
                Curve c = lc.Curve;
                List<Pt> pts;
                if (c is Line line)
                {
                    XYZ a = line.GetEndPoint(0), b = line.GetEndPoint(1);
                    XYZ dir = (b - a).Normalize();
                    XYZ n = new XYZ(-dir.Y, dir.X, 0) * (w.Width / 2);
                    pts = new List<Pt> { P(a + n), P(b + n), P(b - n), P(a - n) };
                }
                else
                {
                    pts = c.Tessellate().Select(P).ToList();
                }
                snap.Outlines.Add(new LiveOutline(w.Id.Value.ToString(), "Wall " + w.Name, pts));
            }

            // Floors: their sketch outline.
            foreach (Floor f in new FilteredElementCollector(doc).OfClass(typeof(Floor)).Cast<Floor>())
            {
                if (doc.GetElement(f.SketchId) is not Sketch sketch)
                    continue;
                foreach (CurveArray loop in sketch.Profile)
                {
                    var pts = new List<Pt>();
                    foreach (Curve c in loop)
                    {
                        IList<XYZ> t = c.Tessellate();
                        for (int i = 0; i + 1 < t.Count; i++)
                            pts.Add(P(t[i]));
                    }
                    if (pts.Count >= 3)
                        snap.Outlines.Add(new LiveOutline(f.Id.Value.ToString(), "Floor " + f.Name, pts));
                }
            }

            // Columns, roofs, stairs, generic models: their plan bounding box.
            double? top = null;
            foreach (BuiltInCategory cat in Boxed)
            {
                foreach (Element e in new FilteredElementCollector(doc).OfCategory(cat).WhereElementIsNotElementType())
                {
                    if (e.get_BoundingBox(null) is not BoundingBoxXYZ bb)
                        continue;
                    top = Math.Max(top ?? bb.Max.Z, bb.Max.Z);
                    if (cat == BuiltInCategory.OST_Roofs)
                        continue; // roof overhangs aren't building footprint for margins
                    snap.Outlines.Add(new LiveOutline(e.Id.Value.ToString(), $"{e.Category?.Name} {e.Name}", new List<Pt>
                    {
                        P(bb.Min), P(new XYZ(bb.Max.X, bb.Min.Y, 0)), P(bb.Max), P(new XYZ(bb.Min.X, bb.Max.Y, 0)),
                    }));
                }
            }
            foreach (Wall w in new FilteredElementCollector(doc).OfClass(typeof(Wall)).Cast<Wall>())
                if (w.get_BoundingBox(null) is BoundingBoxXYZ bb)
                    top = Math.Max(top ?? bb.Max.Z, bb.Max.Z);
            snap.HeightM = top is double t2 ? Math.Round(Units.M(t2 - groundZ), 3) : null;

            snap.BuiltUpM2 = BuiltUp(doc, groundZ);
            ReadValues(doc, snap);
            return snap;
        }

        /// <summary>Gross / BUA area plans if the model has them, else the floor slabs at or above ground.</summary>
        private static double? BuiltUp(Document doc, double groundZ)
        {
            var areas = new FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_Areas).WhereElementIsNotElementType()
                .OfType<RevitArea>().Where(a => a.Area > 0 && CountsToFsi(a.AreaScheme?.Name)).ToList();
            if (areas.Count > 0)
                return Math.Round(areas.Sum(a => Units.M2(a.Area)), 2);
            double total = 0;
            bool any = false;
            foreach (Floor f in new FilteredElementCollector(doc).OfClass(typeof(Floor)).Cast<Floor>())
            {
                if (doc.GetElement(f.LevelId) is Level l && l.ProjectElevation < groundZ - 0.03)
                    continue; // basements don't count here
                Parameter? p = f.get_Parameter(BuiltInParameter.HOST_AREA_COMPUTED);
                if (p is { HasValue: true })
                {
                    total += Units.M2(p.AsDouble());
                    any = true;
                }
            }
            return any ? Math.Round(total, 2) : null;
        }

        private static bool CountsToFsi(string? scheme)
        {
            string s = (scheme ?? "").ToLowerInvariant();
            return s.Contains("gross") || s.Contains("bua") || s.Contains("fsi") || s.Contains("built");
        }

        private static void ReadValues(Document doc, LiveSnapshot snap)
        {
            foreach (Room r in new FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_Rooms)
                         .WhereElementIsNotElementType().OfType<Room>())
            {
                if (r.Area <= 0)
                    continue;
                snap.Values[r.UniqueId] = new Dictionary<string, double?> { ["clear_height_m"] = Math.Round(Units.M(r.UnboundedHeight), 3) };
            }
            foreach (FamilyInstance d in new FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_Doors)
                         .WhereElementIsNotElementType().OfType<FamilyInstance>())
            {
                snap.Values[d.UniqueId] = new Dictionary<string, double?>
                {
                    ["width_m"] = RevitExporter.Length(d, BuiltInParameter.DOOR_WIDTH) ?? RevitExporter.Length(d, BuiltInParameter.FAMILY_WIDTH_PARAM),
                    ["height_m"] = RevitExporter.Length(d, BuiltInParameter.DOOR_HEIGHT) ?? RevitExporter.Length(d, BuiltInParameter.FAMILY_HEIGHT_PARAM),
                };
            }
            foreach (Stairs s in new FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_Stairs)
                         .WhereElementIsNotElementType().OfType<Stairs>())
            {
                try
                {
                    double? minWidth = null;
                    foreach (ElementId runId in s.GetStairsRuns())
                        if (doc.GetElement(runId) is StairsRun run)
                            minWidth = Math.Min(minWidth ?? double.MaxValue, Units.M(run.ActualRunWidth));
                    snap.Values[s.UniqueId] = new Dictionary<string, double?>
                    {
                        ["min_run_width_m"] = minWidth,
                        ["riser_m"] = Units.M(s.ActualRiserHeight),
                        ["tread_m"] = Units.M(s.ActualTreadDepth),
                    };
                }
                catch (Exception)
                {
                    // a stair Revit can't measure right now (mid-edit): skip it this round
                }
            }
        }

        private static Pt P(XYZ p) => new(Units.M(p.X), Units.M(p.Y));
    }
}
