using System;
using System.Collections.Generic;
using System.Linq;
using Autodesk.Revit.DB;
using Autodesk.Revit.DB.Events;
using Autodesk.Revit.UI;
using Autodesk.Revit.UI.Events;
using ComplianceChecker.Core.Live;
using ComplianceChecker.Export;
using ComplianceChecker.Results;
using ComplianceChecker.UI;

namespace ComplianceChecker.Live
{
    /// <summary>
    /// Live mode. After a check, the server's live pack is kept per document. While the
    /// user models, edits are noted (DocumentChanged); once nothing has changed for 1.5 s the model
    /// is re-read and the live engine runs (Idling): the live panel on the left (FSI bar, height,
    /// setbacks) and the strip in the results pane update, and the lens redraws (on by default: the
    /// buildable line, the part of an element past it, the height limit). One alert when the FSI or
    /// the height first goes over its limit, none after; new elements get a 10 s grace before a
    /// setback is flagged; nothing is ever written to the model.
    /// </summary>
    internal sealed class LiveController
    {
        private static readonly TimeSpan Settle = TimeSpan.FromSeconds(1.5);
        private static readonly TimeSpan Grace = TimeSpan.FromSeconds(10);

        private readonly ResultsPane _pane;
        private readonly LiveGauge _gauge;
        private readonly LensServer _lens;
        private readonly HashSet<string> _alerted = new();
        private readonly Dictionary<string, LivePack> _packs = new();
        private readonly Dictionary<long, DateTime> _born = new();
        private DateTime _lastChange = DateTime.MinValue;
        private bool _dirty;

        public LiveController(ResultsPane pane, LiveGauge gauge, LensServer lens)
        {
            _pane = pane;
            _gauge = gauge;
            _lens = lens;
            _lens.Enabled = true;
            _pane.LensToggled += on => LensOn = on;
        }

        public bool LensOn
        {
            get => _lens.Enabled;
            set
            {
                _lens.Enabled = value;
                _pane.SetLensChecked(value);
                _dirty = true;
                _lastChange = DateTime.MinValue; // redraw at the next idle
            }
        }

        public bool HasPack(Document doc) => _packs.ContainsKey(Key(doc));

        public static string Key(Document doc) => string.IsNullOrEmpty(doc.PathName) ? doc.Title : doc.PathName;

        public void Hook(UIControlledApplication app)
        {
            app.ControlledApplication.DocumentChanged += OnChanged;
            app.Idling += OnIdling;
        }

        public void Unhook(UIControlledApplication app)
        {
            app.ControlledApplication.DocumentChanged -= OnChanged;
            app.Idling -= OnIdling;
        }

        /// <summary>Main thread: a fresh pack arrived with a check's results.</summary>
        public void SetPack(UIApplication app, string docKey, LivePack? pack)
        {
            if (pack is null)
            {
                _packs.Remove(docKey);
            }
            else
            {
                _packs[docKey] = pack;
                _pane.SetLensChecked(LensOn);
                try
                {
                    app.GetDockablePane(App.LivePaneId).Show();
                }
                catch (Exception)
                {
                    // the pane isn't available in this Revit session; the results pane still shows the strip
                }
            }
            _dirty = true;
            _lastChange = DateTime.MinValue;
        }

        private void OnChanged(object? sender, DocumentChangedEventArgs e)
        {
            if (!_packs.ContainsKey(Key(e.GetDocument())))
                return;
            DateTime now = DateTime.Now;
            foreach (ElementId id in e.GetAddedElementIds())
                _born[id.Value] = now;
            _dirty = true;
            _lastChange = now;
        }

        private void OnIdling(object? sender, IdlingEventArgs e)
        {
            if (!_dirty || DateTime.Now - _lastChange < Settle || sender is not UIApplication app)
                return;
            Document? doc = app.ActiveUIDocument?.Document;
            if (doc is null || !_packs.TryGetValue(Key(doc), out LivePack? pack))
                return;
            _dirty = false;
            try
            {
                LiveSnapshot snap = LiveSnapshotReader.Read(doc);
                LiveStatus status = LiveEngine.Evaluate(pack, snap);

                // Grace: an element created moments ago isn't flagged yet; look again when it expires.
                DateTime now = DateTime.Now;
                var young = status.Setbacks.Where(s => long.TryParse(s.ElementId, out long id) &&
                                                       _born.TryGetValue(id, out DateTime t) && now - t < Grace).ToList();
                if (young.Count > 0)
                {
                    status = status with { Setbacks = status.Setbacks.Except(young).ToList() };
                    _dirty = true;
                    _lastChange = now - Settle + Grace / 2;
                }
                foreach (long old in _born.Where(kv => now - kv.Value > Grace).Select(kv => kv.Key).ToList())
                    _born.Remove(old);

                _pane.ShowLive(status, LensOn);
                _gauge.Show(status);
                Alert(Key(doc), status);
                var levels = new FilteredElementCollector(doc).OfClass(typeof(Level)).Cast<Level>().ToList();
                double groundFeet = RevitExporter.GroundLevel(levels)?.ProjectElevation ?? 0;
                if (LensOn)
                    _lens.Update(Key(doc), pack, snap, status, groundFeet);
                else
                    _lens.Clear();
                app.ActiveUIDocument?.RefreshActiveView();
            }
            catch (Exception ex)
            {
                // Live mode is a convenience: a model mid-edit that can't be read now is read next time.
                _pane.ShowLiveError(ex.Message);
            }
        }

        /// <summary>One dialog when the FSI or the height first goes over its limit; again only after it came back within.</summary>
        private void Alert(string docKey, LiveStatus s)
        {
            var lines = new List<string>();
            foreach (var (key, over, text) in new[]
            {
                ("fsi", s.FsiOver, $"FSI {s.Fsi:0.00} is over the maximum {s.FsiMax:0.00}: {-(s.FsiLeftM2 ?? 0):0} m² of built-up area too much."),
                ("height", s.HeightOver, $"The building is {s.HeightM:0.0} m tall; the limit here is {s.HeightLimitM:0.0} m{(s.HeightClauseRef is { } c ? $" (UDCPR {c})" : "")}."),
            })
            {
                string k = docKey + "|" + key;
                if (!over)
                    _alerted.Remove(k);
                else if (_alerted.Add(k))
                    lines.Add(text);
            }
            if (lines.Count > 0)
                TaskDialog.Show("Datum", string.Join("\n\n", lines) + "\n\nLive preview: Run Check for the full report.");
        }
    }
}
