using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.RegularExpressions;
using Autodesk.Revit.DB;
using Autodesk.Revit.DB.Architecture;
using ComplianceChecker.Core.Model;
using RevitArea = Autodesk.Revit.DB.Area;

namespace ComplianceChecker.Export
{
    /// <summary>
    /// Reads the open Revit document into a <see cref="RawModel"/> (SI units, model coordinates).
    /// Read-only (D11): the only transaction it opens is rolled back (used to compute room volumes).
    /// Anything it can't read is left null and listed in <see cref="RawModel.Warnings"/>.
    /// </summary>
    public static class RevitExporter
    {
        private static readonly Regex GroundName = new(@"\b(ground|gf|g\.f\.|level 0|level 00|lvl 0)\b", RegexOptions.IgnoreCase);

        public static RawModel Read(Document doc, string toolVersion)
        {
            var raw = new RawModel
            {
                ProjectName = SafeString(() => doc.ProjectInformation?.Name) is { Length: > 0 } n ? n : doc.Title,
                SourceFile = string.IsNullOrEmpty(doc.PathName) ? doc.Title : System.IO.Path.GetFileName(doc.PathName),
                ToolVersion = $"{toolVersion} / Revit {doc.Application.VersionNumber}",
            };

            ReadLocation(doc, raw);
            var levels = new FilteredElementCollector(doc).OfClass(typeof(Level)).Cast<Level>().ToList();
            foreach (Level l in levels)
                raw.Levels.Add(new RawLevel(LevelId(l.Id), l.UniqueId, l.Name, Units.M(l.ProjectElevation)));
            Level? ground = GroundLevel(levels);
            raw.GroundLevelM = ground is null ? null : Units.M(ground.ProjectElevation);

            ReadRoomsWithVolumes(doc, raw);
            ReadAreas(doc, raw);
            ReadStairs(doc, raw);
            ReadDoors(doc, raw);
            ReadPropertyLines(doc, raw);
            raw.Footprint = Footprint(doc, ground, raw);
            ReadHeights(doc, levels, raw);
            return raw;
        }

        /// <summary>Just the site: property lines, footprint and location (for Site Setup; fast).</summary>
        public static RawModel ReadSite(Document doc)
        {
            var raw = new RawModel { ProjectName = doc.Title };
            ReadLocation(doc, raw);
            var levels = new FilteredElementCollector(doc).OfClass(typeof(Level)).Cast<Level>().ToList();
            Level? ground = GroundLevel(levels);
            ReadPropertyLines(doc, raw);
            raw.Footprint = Footprint(doc, ground, raw);
            return raw;
        }

        // ------------------------------------------------------------------ project & levels

        private static void ReadLocation(Document doc, RawModel raw)
        {
            try
            {
                SiteLocation site = doc.SiteLocation;
                raw.Latitude = site.Latitude * 180.0 / Math.PI;   // Revit stores radians
                raw.Longitude = site.Longitude * 180.0 / Math.PI;
            }
            catch (Exception e)
            {
                raw.Warnings.Add($"Project location not read: {e.Message}");
            }
        }

        /// <summary>A level named like "Ground"/"GF", else the lowest level at or above elevation 0.</summary>
        internal static Level? GroundLevel(List<Level> levels)
        {
            Level? named = levels.FirstOrDefault(l => GroundName.IsMatch(l.Name));
            if (named is not null)
                return named;
            const double tol = 0.03; // feet ≈ 1 cm
            return levels.Where(l => l.ProjectElevation >= -tol).OrderBy(l => l.ProjectElevation).FirstOrDefault()
                   ?? levels.OrderBy(l => l.ProjectElevation).FirstOrDefault();
        }

        // ------------------------------------------------------------------ rooms

        private static void ReadRoomsWithVolumes(Document doc, RawModel raw)
        {
            var rooms = new FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_Rooms)
                .WhereElementIsNotElementType().OfType<Room>().Where(r => r.Area > 0 && r.Location != null).ToList();
            if (rooms.Count == 0)
            {
                raw.Warnings.Add("No placed, enclosed rooms found: room checks will be 'cannot verify'.");
                return;
            }

            // Room volumes give the average clear height (volume ÷ area). Volume computation is a
            // document setting, so turn it on inside a transaction, read, and roll back: no change.
            using var t = new Transaction(doc, "Datum: read room volumes");
            bool rolledBack = false;
            try
            {
                if (doc.IsModifiable || doc.IsReadOnly)
                    throw new InvalidOperationException("document can't start a transaction now");
                t.Start();
                AreaVolumeSettings.GetAreaVolumeSettings(doc).ComputeVolumes = true;
                doc.Regenerate();
                foreach (Room r in rooms)
                    raw.Rooms.Add(ReadRoom(r, withVolume: true));
                t.RollBack();
                rolledBack = true;
            }
            catch (Exception e)
            {
                if (t.HasStarted() && !rolledBack)
                    t.RollBack();
                raw.Warnings.Add($"Room heights not computed ({e.Message}); rooms exported without clear height.");
                raw.Rooms.Clear();
                foreach (Room r in rooms)
                    raw.Rooms.Add(ReadRoom(r, withVolume: false));
            }
        }

        private static RawRoom ReadRoom(Room r, bool withVolume)
        {
            double? height = null;
            string? note = null;
            if (withVolume && r.Volume > 0 && r.Area > 0)
            {
                height = Units.M(r.Volume / r.Area); // ft³ / ft² = ft
                note = "average clear height from room volume";
            }
            else
            {
                note = "clear height not available";
            }
            return new RawRoom(
                RoomId(r.Id), r.UniqueId, Name(r), LevelId(r.LevelId), Units.M2(r.Area), height,
                OuterLoop(r.GetBoundarySegments(new SpatialElementBoundaryOptions
                {
                    SpatialElementBoundaryLocation = SpatialElementBoundaryLocation.Finish,
                })), note);
        }

        // ------------------------------------------------------------------ areas (FSI + units)

        private static void ReadAreas(Document doc, RawModel raw)
        {
            foreach (RevitArea a in new FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_Areas)
                         .WhereElementIsNotElementType().OfType<RevitArea>().Where(a => a.Area > 0))
            {
                raw.Areas.Add(new RawArea(AreaId(a.Id), a.UniqueId, a.AreaScheme?.Name ?? "", LevelId(a.LevelId), Name(a), Units.M2(a.Area)));
            }
        }

        // ------------------------------------------------------------------ stairs & doors

        private static void ReadStairs(Document doc, RawModel raw)
        {
            foreach (Stairs s in new FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_Stairs)
                         .WhereElementIsNotElementType().OfType<Stairs>())
            {
                try
                {
                    double? minWidth = null;
                    foreach (ElementId runId in s.GetStairsRuns())
                        if (doc.GetElement(runId) is StairsRun run)
                            minWidth = Math.Min(minWidth ?? double.MaxValue, Units.M(run.ActualRunWidth));
                    ElementId baseLevel = s.get_Parameter(BuiltInParameter.STAIRS_BASE_LEVEL_PARAM)?.AsElementId() ?? ElementId.InvalidElementId;
                    ElementId topLevel = s.get_Parameter(BuiltInParameter.STAIRS_TOP_LEVEL_PARAM)?.AsElementId() ?? ElementId.InvalidElementId;
                    raw.Stairs.Add(new RawStair(
                        StairId(s.Id), s.UniqueId, LevelId(baseLevel),
                        topLevel == ElementId.InvalidElementId ? null : LevelId(topLevel),
                        minWidth, Units.M(s.ActualRiserHeight), Units.M(s.ActualTreadDepth)));
                }
                catch (Exception e)
                {
                    raw.Warnings.Add($"Stair {s.Id.Value} skipped: {e.Message}");
                }
            }
        }

        private static void ReadDoors(Document doc, RawModel raw)
        {
            Phase? phase = doc.Phases.Size > 0 ? doc.Phases.get_Item(doc.Phases.Size - 1) : null;
            foreach (FamilyInstance d in new FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_Doors)
                         .WhereElementIsNotElementType().OfType<FamilyInstance>())
            {
                double? width = Length(d, BuiltInParameter.DOOR_WIDTH) ?? Length(d, BuiltInParameter.FAMILY_WIDTH_PARAM);
                double? height = Length(d, BuiltInParameter.DOOR_HEIGHT) ?? Length(d, BuiltInParameter.FAMILY_HEIGHT_PARAM);
                Room? from = null, to = null;
                try
                {
                    from = phase is null ? d.FromRoom : d.get_FromRoom(phase);
                    to = phase is null ? d.ToRoom : d.get_ToRoom(phase);
                }
                catch (Exception)
                {
                    // rooms can't be resolved for this door; leave both unknown
                }
                ElementId level = d.LevelId != ElementId.InvalidElementId ? d.LevelId : (d.Host as Wall)?.LevelId ?? ElementId.InvalidElementId;
                raw.Doors.Add(new RawDoor(DoorId(d.Id), d.UniqueId, LevelId(level), width, height,
                    from is null ? null : RoomId(from.Id), to is null ? null : RoomId(to.Id)));
            }
        }

        /// <summary>A length parameter from the instance, else its type, in metres.</summary>
        internal static double? Length(FamilyInstance fi, BuiltInParameter bip)
        {
            Parameter? p = fi.get_Parameter(bip);
            if (p is null || !p.HasValue)
                p = fi.Symbol?.get_Parameter(bip);
            return p is { HasValue: true, StorageType: StorageType.Double } ? Units.M(p.AsDouble()) : null;
        }

        // ------------------------------------------------------------------ site

        private static void ReadPropertyLines(Document doc, RawModel raw)
        {
            var options = new Options { ComputeReferences = false, IncludeNonVisibleObjects = true };
            foreach (Element e in new FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_SiteProperty)
                         .WhereElementIsNotElementType())
            {
                GeometryElement? geom = e.get_Geometry(options);
                if (geom is not null)
                    CollectSegments(geom, raw.PropertyLineSegments);
            }
            if (raw.PropertyLineSegments.Count == 0)
                raw.Warnings.Add("No property lines: draw them (Massing & Site › Property Line) so margins and FSI can be checked.");
        }

        private static void CollectSegments(GeometryElement geom, List<(Pt A, Pt B)> into)
        {
            foreach (GeometryObject obj in geom)
            {
                if (obj is Curve c)
                {
                    IList<XYZ> pts = c.Tessellate();
                    for (int i = 0; i + 1 < pts.Count; i++)
                        into.Add((P(pts[i]), P(pts[i + 1])));
                }
                else if (obj is GeometryInstance gi)
                {
                    CollectSegments(gi.GetInstanceGeometry(), into);
                }
            }
        }

        /// <summary>Outline of the largest floor on the ground level, else the ground-floor gross area.</summary>
        private static List<Pt>? Footprint(Document doc, Level? ground, RawModel raw)
        {
            if (ground is null)
                return null;
            var floors = new FilteredElementCollector(doc).OfClass(typeof(Floor)).Cast<Floor>()
                .Where(f => f.LevelId == ground.Id).ToList();
            List<Pt>? best = null;
            foreach (Floor f in floors)
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
                    if (pts.Count >= 3 && (best is null || Geometry.Area(pts) > Geometry.Area(best)))
                        best = pts;
                }
            }
            if (best is not null)
                return best;

            var gross = new FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_Areas).WhereElementIsNotElementType()
                .OfType<RevitArea>().Where(a => a.LevelId == ground.Id && a.Area > 0 &&
                                                (a.AreaScheme?.Name ?? "").IndexOf("gross", StringComparison.OrdinalIgnoreCase) >= 0)
                .OrderByDescending(a => a.Area).FirstOrDefault();
            if (gross is not null)
                return OuterLoop(gross.GetBoundarySegments(new SpatialElementBoundaryOptions()));
            raw.Warnings.Add("No ground-floor slab or gross area found: footprint unknown, so setbacks can't be checked.");
            return null;
        }

        private static void ReadHeights(Document doc, List<Level> levels, RawModel raw)
        {
            double? roofTop = MaxZ(doc, BuiltInCategory.OST_Roofs);
            if (roofTop is null && levels.Count > 0)
                roofTop = Units.M(levels.Max(l => l.ProjectElevation)); // flat terrace on the top level
            raw.RoofTopM = roofTop;
            var cats = new[]
            {
                BuiltInCategory.OST_Walls, BuiltInCategory.OST_Roofs, BuiltInCategory.OST_Floors,
                BuiltInCategory.OST_Columns, BuiltInCategory.OST_StructuralColumns, BuiltInCategory.OST_GenericModel,
            };
            double? highest = null;
            foreach (var c in cats)
                if (MaxZ(doc, c) is double z)
                    highest = Math.Max(highest ?? z, z);
            raw.HighestPointM = highest;
        }

        private static double? MaxZ(Document doc, BuiltInCategory cat)
        {
            double? max = null;
            foreach (Element e in new FilteredElementCollector(doc).OfCategory(cat).WhereElementIsNotElementType())
                if (e.get_BoundingBox(null) is BoundingBoxXYZ bb)
                    max = Math.Max(max ?? bb.Max.Z, bb.Max.Z);
            return max is double m ? Units.M(m) : null;
        }

        // ------------------------------------------------------------------ helpers

        private static List<Pt>? OuterLoop(IList<IList<BoundarySegment>>? loops)
        {
            if (loops is null)
                return null;
            List<Pt>? best = null;
            foreach (IList<BoundarySegment> loop in loops)
            {
                var pts = new List<Pt>();
                foreach (BoundarySegment seg in loop)
                {
                    IList<XYZ> t = seg.GetCurve().Tessellate();
                    for (int i = 0; i + 1 < t.Count; i++)
                        pts.Add(P(t[i]));
                }
                if (pts.Count >= 3 && (best is null || Geometry.Area(pts) > Geometry.Area(best)))
                    best = pts;
            }
            return best;
        }

        private static Pt P(XYZ p) => new(Units.M(p.X), Units.M(p.Y));

        private static string Name(SpatialElement e) =>
            e.get_Parameter(BuiltInParameter.ROOM_NAME)?.AsString() is { Length: > 0 } n ? n : e.Name;

        private static string? SafeString(Func<string?> f)
        {
            try { return f(); } catch { return null; }
        }

        public static string LevelId(ElementId id) => "L" + id.Value;
        public static string RoomId(ElementId id) => "R" + id.Value;
        private static string AreaId(ElementId id) => "A" + id.Value;
        private static string StairId(ElementId id) => "S" + id.Value;
        private static string DoorId(ElementId id) => "D" + id.Value;
    }
}
