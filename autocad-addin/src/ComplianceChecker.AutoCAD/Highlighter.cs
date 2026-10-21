using System;
using System.Collections.Generic;
using System.Globalization;
using Autodesk.AutoCAD.ApplicationServices;
using Autodesk.AutoCAD.DatabaseServices;
using Autodesk.AutoCAD.EditorInput;
using Autodesk.AutoCAD.Geometry;
using Autodesk.AutoCAD.GraphicsInterface;
using ComplianceChecker.Core.Results;
using ComplianceChecker.Generated;

namespace ComplianceChecker.AutoCAD
{
    /// <summary>
    /// Shows results on the drawing with transient graphics (P11.4): failing entities get a thick
    /// red copy drawn on top, can't-verify ones a grey one. Transients are display-only: nothing is
    /// added to or changed in the drawing, and they vanish with CCCLEAR or the next check.
    /// </summary>
    internal static class Highlighter
    {
        private static readonly List<Entity> Shown = new();

        public static void Show(Document doc, CheckReport report)
        {
            Clear();
            var view = new ReportView(report);
            Database db = doc.Database;
            using Transaction tr = db.TransactionManager.StartOpenCloseTransaction();
            foreach (KeyValuePair<string, Status> kv in view.ElementStatus)
            {
                if (kv.Value is not (Status.Fail or Status.Unverifiable))
                    continue;
                if (Open(db, tr, kv.Key) is not { } ent)
                    continue;
                var copy = (Entity)ent.Clone();
                copy.ColorIndex = kv.Value == Status.Fail ? 1 : 8; // red, grey
                copy.LineWeight = kv.Value == Status.Fail ? LineWeight.LineWeight060 : LineWeight.LineWeight030;
                TransientManager.CurrentTransientManager.AddTransient(copy, TransientDrawingMode.DirectTopmost, 128, new IntegerCollection());
                Shown.Add(copy);
            }
            tr.Commit();
        }

        public static void Clear()
        {
            foreach (Entity e in Shown)
            {
                TransientManager.CurrentTransientManager.EraseTransient(e, new IntegerCollection());
                e.Dispose();
            }
            Shown.Clear();
        }

        /// <summary>Zoom to an entity (by DXF handle) and select it.</summary>
        public static void ZoomTo(Document doc, string handle)
        {
            Database db = doc.Database;
            Editor ed = doc.Editor;
            using Transaction tr = db.TransactionManager.StartOpenCloseTransaction();
            if (Open(db, tr, handle) is not { } ent)
            {
                ed.WriteMessage($"\nCompliance: entity {handle} is no longer in the drawing.");
                return;
            }
            Extents3d ext = ent.GeometricExtents;
            double w = Math.Max(ext.MaxPoint.X - ext.MinPoint.X, 1), h = Math.Max(ext.MaxPoint.Y - ext.MinPoint.Y, 1);
            using ViewTableRecord view = ed.GetCurrentView();
            double aspect = view.Width / Math.Max(view.Height, 1e-9);
            double height = Math.Max(h, w / aspect) * 2.2;
            view.CenterPoint = new Point2d((ext.MinPoint.X + ext.MaxPoint.X) / 2, (ext.MinPoint.Y + ext.MaxPoint.Y) / 2);
            view.Height = height;
            view.Width = height * aspect;
            ed.SetCurrentView(view);
            ed.SetImpliedSelection(new[] { ent.ObjectId });
            tr.Commit();
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
