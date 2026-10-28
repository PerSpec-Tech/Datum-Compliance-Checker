using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using Autodesk.AutoCAD.ApplicationServices;
using Autodesk.AutoCAD.Colors;
using Autodesk.AutoCAD.DatabaseServices;
using Autodesk.AutoCAD.EditorInput;
using Autodesk.AutoCAD.Geometry;
using Autodesk.AutoCAD.GraphicsInterface;
using Polyline = Autodesk.AutoCAD.DatabaseServices.Polyline;
using ComplianceChecker.Core.Results;
using ComplianceChecker.Generated;

namespace ComplianceChecker.AutoCAD
{
    /// <summary>
    /// Results on the drawing. Each failing element gets a red revision cloud and a short
    /// label on the layer COMPLIANCE ISSUES; can't-verify ones a grey cloud. Every entity the plug-in
    /// adds carries the PERSPEC_COMPLIANCE XData tag, so a re-check or CCCLEAR removes exactly those:
    /// nothing else in the drawing is ever changed. Clicking a result adds a temporary red fill
    /// (a transient, not saved) and zooms to it.
    /// </summary>
    internal static class Highlighter
    {
        public const string LayerName = "COMPLIANCE ISSUES";

        // Clouds: red for a fail, yellow for a check that can't be verified yet (AutoCAD colours 1 and 2).
        private const short Red = 1, Yellow = 2;
        private const string App = "PERSPEC_COMPLIANCE";
        private static readonly List<Entity> Focused = new();

        /// <summary>Redraw the clouds for a report (replacing the previous check's).</summary>
        public static int Show(Document doc, CheckReport report)
        {
            ClearFocus();
            var view = new ReportView(report);
            var rows = view.Groups.SelectMany(g => g.Rows)
                .Where(r => r.Status is Status.Fail or Status.Unverifiable)
                .GroupBy(r => (r.ElementKind, r.ElementId, r.SourceId))
                .ToList();
            Database db = doc.Database;
            double unit = 1 / Markup.MetresPerUnit(db); // drawing units per metre
            int drawn = 0;
            using DocumentLock _ = doc.LockDocument();
            using Transaction tr = db.TransactionManager.StartTransaction();
            EraseOurs(db, tr);
            ObjectId layer = EnsureLayer(db, tr);
            EnsureApp(db, tr);
            var space = (BlockTableRecord)tr.GetObject(db.CurrentSpaceId, OpenMode.ForWrite);
            foreach (var group in rows)
            {
                ResultRow first = group.First();
                if (Outline(db, tr, first, unit) is not { Count: > 0 } outline)
                    continue;
                bool fail = group.Any(r => r.Status == Status.Fail);
                var lead = group.Where(r => r.Status == (fail ? Status.Fail : Status.Unverifiable)).ToList();
                Extents2d box = Markup.Box(outline, 0.4 * unit);
                double size = Math.Max(box.MaxPoint.X - box.MinPoint.X, box.MaxPoint.Y - box.MinPoint.Y);
                double arc = Math.Clamp(size / 10, 0.4 * unit, 2.5 * unit);

                Polyline cloud = Markup.Cloud(box, arc);
                Add(space, tr, cloud, layer, fail ? Red : Yellow);
                var label = new MText
                {
                    Contents = Label(lead),
                    TextHeight = Math.Clamp(arc * 0.45, 0.18 * unit, 0.6 * unit),
                    Location = new Point3d(box.MinPoint.X, box.MaxPoint.Y + arc * 0.6, 0),
                    Attachment = AttachmentPoint.BottomLeft,
                    Width = 0,
                };
                Add(space, tr, label, layer, fail ? Red : Yellow);
                drawn++;
            }
            tr.Commit();
            doc.Editor.Regen();
            return drawn;
        }

        /// <summary>Remove everything the plug-in drew (CCCLEAR).</summary>
        public static void Clear(Document? doc = null)
        {
            ClearFocus();
            if (doc is null)
                return;
            using DocumentLock _ = doc.LockDocument();
            using Transaction tr = doc.Database.TransactionManager.StartTransaction();
            EraseOurs(doc.Database, tr);
            tr.Commit();
        }

        /// <summary>Zoom to one result and fill it red for a moment (transient: not saved).</summary>
        public static void Focus(Document doc, ResultRow row)
        {
            ClearFocus();
            Database db = doc.Database;
            double unit = 1 / Markup.MetresPerUnit(db);
            List<Point2d>? outline;
            using (Transaction tr = db.TransactionManager.StartOpenCloseTransaction())
                outline = Outline(db, tr, row, unit);
            if (outline is not { Count: > 2 })
            {
                doc.Editor.WriteMessage("\nDatum: this result has no place on the drawing (it is about the whole project).");
                return;
            }
            try
            {
                var hatch = new Hatch();
                hatch.SetDatabaseDefaults(db);
                hatch.SetHatchPattern(HatchPatternType.PreDefined, "SOLID");
                var loop = new HatchLoop(HatchLoopTypes.Polyline);
                foreach (Point2d p in outline)
                    loop.Polyline.Add(new BulgeVertex(p, 0));
                loop.Polyline.Add(new BulgeVertex(outline[0], 0));
                hatch.AppendLoop(loop);
                hatch.EvaluateHatch(true);
                hatch.ColorIndex = row.Status == Status.Fail ? Red : Yellow;
                hatch.Transparency = new Transparency(110); // about 57 % see-through
                Transient(hatch);
            }
            catch (System.Exception e)
            {
                Log.Error("focus fill", e); // the zoom and the cloud still show where it is
            }
            Extents2d box = Markup.Box(outline, 0.4 * unit);
            Zoom(doc.Editor, box);
        }

        // ------------------------------------------------------------------ internals

        private static string Label(List<ResultRow> rows)
        {
            ResultRow r = rows[0];
            string mark = r.Status == Status.Fail ? "FAIL" : "CHECK"; // plain text: the Standard style's font has no ✕
            string numbers = r.Measured is null && r.Limit is null ? "" : $"  {r.Measured ?? "—"} / {r.Limit ?? "—"}";
            string more = rows.Count > 1 ? $"  (+{rows.Count - 1} more)" : "";
            return $"{mark} {r.Title}{numbers}  [{r.ClauseRef}]{more}";
        }

        /// <summary>The result's outline in drawing units: its entity, plot side, or the building.</summary>
        private static List<Point2d>? Outline(Database db, Transaction tr, ResultRow r, double unit)
        {
            if (r.SourceId is { } handle && Open(db, tr, handle) is { } ent)
            {
                if (ent is Polyline { Closed: true } pl && pl.NumberOfVertices > 2)
                    return Enumerable.Range(0, pl.NumberOfVertices).Select(pl.GetPoint2dAt).ToList();
                Extents3d e = ent.GeometricExtents;
                return new()
                {
                    new(e.MinPoint.X, e.MinPoint.Y), new(e.MaxPoint.X, e.MinPoint.Y),
                    new(e.MaxPoint.X, e.MaxPoint.Y), new(e.MinPoint.X, e.MaxPoint.Y),
                };
            }
            if (Markup.Current is not { } m)
                return null;
            if (r.ElementKind == "site.edges" && r.ElementId is { } edge)
                return m.Edge(edge, 0.6 * unit);
            return m.Footprint; // the whole building or the plot: cloud the building on the site plan
        }

        private static void Add(BlockTableRecord space, Transaction tr, Entity e, ObjectId layer, int colour)
        {
            e.LayerId = layer;
            e.Color = Color.FromColorIndex(ColorMethod.ByAci, (short)colour);
            e.XData = new ResultBuffer(new TypedValue((int)DxfCode.ExtendedDataRegAppName, App));
            space.AppendEntity(e);
            tr.AddNewlyCreatedDBObject(e, true);
        }

        private static void EraseOurs(Database db, Transaction tr)
        {
            var bt = (BlockTable)tr.GetObject(db.BlockTableId, OpenMode.ForRead);
            foreach (ObjectId spaceId in bt)
            {
                var space = (BlockTableRecord)tr.GetObject(spaceId, OpenMode.ForRead);
                if (!space.IsLayout)
                    continue;
                foreach (ObjectId id in space)
                {
                    if (id.IsErased || tr.GetObject(id, OpenMode.ForRead) is not Entity e)
                        continue;
                    if (e.GetXDataForApplication(App) is { } xd)
                    {
                        xd.Dispose();
                        e.UpgradeOpen();
                        e.Erase();
                    }
                }
            }
        }

        private static ObjectId EnsureLayer(Database db, Transaction tr)
        {
            var layers = (LayerTable)tr.GetObject(db.LayerTableId, OpenMode.ForRead);
            if (layers.Has(LayerName))
                return layers[LayerName];
            var ltr = new LayerTableRecord
            {
                Name = LayerName,
                Color = Color.FromColorIndex(ColorMethod.ByAci, 1),
                LineWeight = LineWeight.LineWeight050,
                Description = "Datum by PerSpec: compliance issues. Redrawn by every check; CCCLEAR removes them.",
            };
            layers.UpgradeOpen();
            ObjectId id = layers.Add(ltr);
            tr.AddNewlyCreatedDBObject(ltr, true);
            return id;
        }

        private static void EnsureApp(Database db, Transaction tr)
        {
            var apps = (RegAppTable)tr.GetObject(db.RegAppTableId, OpenMode.ForRead);
            if (apps.Has(App))
                return;
            apps.UpgradeOpen();
            var rec = new RegAppTableRecord { Name = App };
            apps.Add(rec);
            tr.AddNewlyCreatedDBObject(rec, true);
        }

        private static void Transient(Entity e)
        {
            TransientManager.CurrentTransientManager.AddTransient(e, TransientDrawingMode.DirectShortTerm, 128, new IntegerCollection());
            Focused.Add(e);
        }

        private static void ClearFocus()
        {
            foreach (Entity e in Focused)
            {
                TransientManager.CurrentTransientManager.EraseTransient(e, new IntegerCollection());
                e.Dispose();
            }
            Focused.Clear();
        }

        private static void Zoom(Editor ed, Extents2d box)
        {
            double w = Math.Max(box.MaxPoint.X - box.MinPoint.X, 1e-6), h = Math.Max(box.MaxPoint.Y - box.MinPoint.Y, 1e-6);
            using ViewTableRecord view = ed.GetCurrentView();
            double aspect = view.Width / Math.Max(view.Height, 1e-9);
            double height = Math.Max(h, w / aspect) * 1.8;
            view.CenterPoint = new Point2d((box.MinPoint.X + box.MaxPoint.X) / 2, (box.MinPoint.Y + box.MaxPoint.Y) / 2);
            view.Height = height;
            view.Width = height * aspect;
            ed.SetCurrentView(view);
        }

        private static Entity? Open(Database db, Transaction tr, string handle)
        {
            if (!long.TryParse(handle, NumberStyles.HexNumber, CultureInfo.InvariantCulture, out long value))
                return null;
            if (!db.TryGetObjectId(new Handle(value), out ObjectId id) || id.IsErased)
                return null;
            return tr.GetObject(id, OpenMode.ForRead) as Entity;
        }
    }
}
