using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Text.Json;
using System.Threading.Tasks;
using Autodesk.AutoCAD.ApplicationServices;
using Autodesk.AutoCAD.DatabaseServices;
using Autodesk.AutoCAD.Geometry;
using Autodesk.AutoCAD.GraphicsInterface;
using Autodesk.AutoCAD.Runtime;
using Autodesk.AutoCAD.Windows;
using ComplianceChecker.Core.Api;
using ComplianceChecker.Core.Live;
using ComplianceChecker.Core.Model;
using AcApp = Autodesk.AutoCAD.ApplicationServices.Application;
using Polyline = Autodesk.AutoCAD.DatabaseServices.Polyline;

namespace ComplianceChecker.AutoCAD
{
    /// <summary>
    /// Live preview while drawing (P11.4, D32): after a check, the margins and FSI are measured again
    /// on every edit, against the live pack the server compiled from the rules. Edits are noticed
    /// through the database events, and measured once AutoCAD is idle and the drawing has been still
    /// for a moment. Local geometry only: no network, no model, milliseconds. The full check stays
    /// the official result.
    ///
    /// Calm by design: never modal, never a sound. The result is one line on the status bar; the
    /// lens (the buildable line, crossing outlines in red with the shortfall) is off until asked for,
    /// and is drawn as transient graphics, so the drawing and its undo history are untouched.
    /// </summary>
    internal static class LiveMode
    {
        private const int StillMs = 700;
        private static readonly RXClass PolylineClass = RXObject.GetClass(typeof(Polyline));

        private static Document? _doc;
        private static LivePack? _pack;
        private static DrawingLive? _drawing;
        private static LiveStatus? _status;
        private static bool _on = true;
        private static bool _lens;
        private static bool _dirty;
        private static DateTime _changed;
        private static Pane? _pane;
        private static readonly List<Entity> LensEntities = new();

        public static bool IsOn => _on;
        public static bool LensOn => _lens;

        /// <summary>After a check: fetch the live pack and the floor frames, then measure.</summary>
        public static async Task StartAsync(Document doc, ApiClient api, string projectId)
        {
            Stop(keepPane: true);
            LivePack? pack = await api.GetLivePackAsync(projectId);
            DrawingFrames frames = await api.GetDrawingFramesAsync(projectId);
            if (pack is null)
            {
                SetPane("Datum: no live preview for this drawing (run the check again).", null);
                return;
            }
            _doc = doc;
            _pack = pack;
            _drawing = new DrawingLive(frames, RoomNames(await api.GetModelJsonAsync(projectId)));
            _drawing.SetBaseline(ReadPolylines(doc.Database));
            doc.Database.ObjectModified += OnChanged;
            doc.Database.ObjectAppended += OnChanged;
            doc.Database.ObjectErased += OnErased;
            AcApp.Idle += OnIdle;
            AcApp.DocumentManager.DocumentActivated += OnActivated;
            AcApp.DocumentManager.DocumentToBeDestroyed += OnClosing;
            Log.Info($"live: {frames.Floors.Count} floor plans, {pack.Edges.Count} sides, envelope {(pack.Envelope?.Count ?? 0)} pts");
            Evaluate();
        }

        public static void Stop(bool keepPane = false)
        {
            if (_doc is { } doc)
            {
                try
                {
                    doc.Database.ObjectModified -= OnChanged;
                    doc.Database.ObjectAppended -= OnChanged;
                    doc.Database.ObjectErased -= OnErased;
                }
                catch (System.Exception)
                {
                    // the drawing is already closing
                }
            }
            AcApp.Idle -= OnIdle;
            AcApp.DocumentManager.DocumentActivated -= OnActivated;
            AcApp.DocumentManager.DocumentToBeDestroyed -= OnClosing;
            ClearLens();
            (_doc, _pack, _drawing, _status, _dirty) = (null, null, null, null, false);
            if (!keepPane)
                RemovePane();
        }

        /// <summary>CCLIVE: pause or resume the live preview (the last check's results stay).</summary>
        public static string Toggle()
        {
            _on = !_on;
            if (!_on)
            {
                ClearLens();
                SetPane("Datum: live preview paused (CCLIVE to resume).", null);
                return "live preview paused.";
            }
            if (_pack is null)
                return "live preview on; it starts after the next check (Datum › 4 Run Check).";
            Evaluate();
            return "live preview on.";
        }

        /// <summary>CCLENS: show or hide the buildable line and the crossing outlines.</summary>
        public static string ToggleLens()
        {
            _lens = !_lens;
            if (_pack is null)
                return _lens ? "lens on; it shows after the next check." : "lens off.";
            Draw();
            return _lens ? "lens on: the buildable line in grey, crossing outlines in red." : "lens off.";
        }

        // ------------------------------------------------------------------ events

        private static void OnChanged(object? sender, ObjectEventArgs e)
        {
            // Our own clouds and labels, and anything that isn't a curve, don't change the result.
            if (e.DBObject is Curve c && !string.Equals(c.Layer, Highlighter.LayerName, StringComparison.OrdinalIgnoreCase))
                MarkDirty();
        }

        private static void OnErased(object? sender, ObjectErasedEventArgs e)
        {
            if (e.DBObject is Curve)
                MarkDirty();
        }

        private static void MarkDirty()
        {
            _dirty = true;
            _changed = DateTime.UtcNow;
        }

        private static void OnIdle(object? sender, EventArgs e)
        {
            if (!_dirty || !_on || (DateTime.UtcNow - _changed).TotalMilliseconds < StillMs)
                return;
            if (AcApp.DocumentManager.MdiActiveDocument != _doc)
                return;
            _dirty = false;
            Evaluate();
        }

        private static void OnActivated(object? sender, DocumentCollectionEventArgs e)
        {
            if (e.Document == _doc)
            {
                Evaluate();
                return;
            }
            ClearLens();
            SetPane("Datum: live preview is on another drawing.", null);
        }

        private static void OnClosing(object? sender, DocumentCollectionEventArgs e)
        {
            if (e.Document == _doc)
                Stop();
        }

        // ------------------------------------------------------------------ measure and show

        private static void Evaluate()
        {
            if (!_on || _doc is not { } doc || _pack is not { } pack || _drawing is not { } drawing)
                return;
            try
            {
                var started = DateTime.UtcNow;
                LiveSnapshot snap = drawing.Snapshot(ReadPolylines(doc.Database), pack.Fsi.UsedM2);
                _status = LiveEngine.Evaluate(pack, snap);
                SetPane("Datum (preview): " + _status.StripText(), Tooltip(_status));
                Draw();
                Log.Info($"live: {_status.StripText()} ({(DateTime.UtcNow - started).TotalMilliseconds:0} ms)");
            }
            catch (System.Exception e)
            {
                Log.Error("live", e);
                SetPane("Datum: live preview stopped (details in the log).", e.Message);
            }
        }

        /// <summary>The closed polylines on the layers the live checks use, in drawing units.</summary>
        private static List<DrawingPolyline> ReadPolylines(Database db)
        {
            var list = new List<DrawingPolyline>();
            if (_drawing is null)
                return list;
            using Transaction tr = db.TransactionManager.StartOpenCloseTransaction();
            var ms = (BlockTableRecord)tr.GetObject(SymbolUtilityServices.GetBlockModelSpaceId(db), OpenMode.ForRead);
            foreach (ObjectId id in ms)
            {
                if (id.IsErased || !id.ObjectClass.IsDerivedFrom(PolylineClass))
                    continue;
                var pl = (Polyline)tr.GetObject(id, OpenMode.ForRead);
                if (_drawing?.Watches(pl.Layer) != true || pl.NumberOfVertices < 3)
                    continue;
                var pts = Enumerable.Range(0, pl.NumberOfVertices).Select(i => pl.GetPoint2dAt(i)).Select(p => new Pt(p.X, p.Y)).ToList();
                if (!pl.Closed && pts[0] != pts[^1])
                    continue;
                list.Add(new DrawingPolyline(pl.Handle.ToString(), pl.Layer, pts));
            }
            return list;
        }

        private static string? Tooltip(LiveStatus s)
        {
            var lines = new List<string> { "Live preview: the full check stays the official result. Click to show or hide the lens." };
            foreach (var side in s.Setbacks.GroupBy(x => x.EdgeId))
            {
                SetbackIssue worst = side.OrderBy(x => x.DistanceM).First();
                string what = string.Join(", ", side.Select(x => x.Label).Distinct().Take(4));
                lines.Add(string.Create(CultureInfo.InvariantCulture,
                    $"Side {side.Key} ({worst.EdgeKind ?? "side"}): {worst.DistanceM:0.00} m, needs {worst.RequiredM:0.00} m ({worst.ClauseRef}). {what}"));
            }
            if (s.FsiLeftM2 is double left && left < 0)
                lines.Add(string.Create(CultureInfo.InvariantCulture, $"FSI: {-left:0} m² over the maximum permissible built-up area."));
            return string.Join("\n", lines);
        }

        // ------------------------------------------------------------------ lens

        private static void Draw()
        {
            ClearLens();
            if (!_lens || !_on || _doc is not { } doc || _pack is not { } pack || _drawing is not { } drawing || _status is not { } status)
                return;
            double unit = 1 / drawing.Scale; // one metre in drawing units
            if (pack.Envelope is { Count: > 2 } env)
            {
                var plot = env.Select(p => new Pt(p[0], p[1])).ToList();
                AddLens(Outline(plot.Select(p => new Pt(p.X * unit, p.Y * unit)), 8, 0.05 * unit)); // site plan
                foreach (FloorFrame f in drawing.Floors)
                    AddLens(Outline(plot.Select(p => drawing.ToDrawing(p, f)), 8, 0.05 * unit));
            }
            var byElement = status.Setbacks.GroupBy(x => x.ElementId);
            using Transaction tr = doc.Database.TransactionManager.StartOpenCloseTransaction();
            foreach (var issues in byElement)
            {
                if (Open(doc.Database, tr, issues.Key) is not Polyline pl)
                    continue;
                SetbackIssue worst = issues.OrderByDescending(x => x.DeficitM).First();
                var pts = Enumerable.Range(0, pl.NumberOfVertices).Select(i => pl.GetPoint2dAt(i)).Select(p => new Pt(p.X, p.Y)).ToList();
                AddLens(Outline(pts, (short)(worst.Slight ? 11 : 1), (worst.Slight ? 0.03 : 0.08) * unit));
                var box = Markup.Box(pts.Select(p => new Point2d(p.X, p.Y)), 0);
                AddLens(new DBText
                {
                    TextString = string.Create(CultureInfo.InvariantCulture, $"{worst.EdgeId}: {worst.DistanceM:0.00} < {worst.RequiredM:0.00} m"),
                    Position = new Point3d(box.MinPoint.X + 0.2 * unit, box.MaxPoint.Y - 0.6 * unit, 0),
                    Height = 0.35 * unit,
                    ColorIndex = worst.Slight ? 11 : 1,
                });
            }
            doc.Editor.UpdateScreen();
        }

        private static Polyline Outline(IEnumerable<Pt> pts, short color, double width)
        {
            var list = pts.ToList();
            var pl = new Polyline(list.Count);
            for (int i = 0; i < list.Count; i++)
                pl.AddVertexAt(i, new Point2d(list[i].X, list[i].Y), 0, 0, 0);
            pl.Closed = true;
            pl.ColorIndex = color;
            pl.ConstantWidth = width;
            return pl;
        }

        private static void AddLens(Entity e)
        {
            TransientManager.CurrentTransientManager.AddTransient(e, TransientDrawingMode.DirectShortTerm, 128, new IntegerCollection());
            LensEntities.Add(e);
        }

        private static void ClearLens()
        {
            foreach (Entity e in LensEntities)
            {
                TransientManager.CurrentTransientManager.EraseTransient(e, new IntegerCollection());
                e.Dispose();
            }
            LensEntities.Clear();
        }

        private static Entity? Open(Database db, Transaction tr, string handle)
        {
            if (!long.TryParse(handle, NumberStyles.HexNumber, CultureInfo.InvariantCulture, out long value))
                return null;
            if (!db.TryGetObjectId(new Handle(value), out ObjectId id) || id.IsErased)
                return null;
            return tr.GetObject(id, OpenMode.ForRead) as Entity;
        }

        // ------------------------------------------------------------------ status bar

        private static void SetPane(string text, string? tip)
        {
            try
            {
                if (_pane is null)
                {
                    _pane = new Pane { Style = PaneStyles.Normal | PaneStyles.PopUp, Visible = true, Enabled = true };
                    _pane.MouseDown += (_, _) =>
                        AcApp.DocumentManager.MdiActiveDocument?.Editor.WriteMessage("\nDatum: " + ToggleLens());
                    AcApp.StatusBar.Panes.Add(_pane);
                }
                _pane.Text = text;
                _pane.ToolTipText = tip ?? text;
                AcApp.StatusBar.Update();
            }
            catch (System.Exception e)
            {
                Log.Error("status bar", e);
            }
        }

        private static void RemovePane()
        {
            if (_pane is null)
                return;
            try
            {
                AcApp.StatusBar.Panes.Remove(_pane);
                AcApp.StatusBar.Update();
            }
            catch (System.Exception)
            {
                // AutoCAD is closing
            }
            _pane = null;
        }

        private static Dictionary<string, string> RoomNames(string modelJson)
        {
            var names = new Dictionary<string, string>();
            using var json = JsonDocument.Parse(modelJson);
            if (json.RootElement.GetProperty("model").TryGetProperty("spaces", out JsonElement spaces))
                foreach (JsonElement s in spaces.EnumerateArray())
                    if (s.TryGetProperty("source_id", out var sid) && sid.ValueKind == JsonValueKind.String &&
                        s.TryGetProperty("name", out var n) && n.ValueKind == JsonValueKind.String)
                        names[sid.GetString()!] = n.GetString()!;
            return names;
        }
    }
}
