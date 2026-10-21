using System;
using System.Linq;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Documents;
using System.Windows.Media;
using Autodesk.AutoCAD.ApplicationServices;
using Autodesk.AutoCAD.Windows;
using ComplianceChecker.Core.Results;
using ComplianceChecker.Generated;
using AcApp = Autodesk.AutoCAD.ApplicationServices.Application;

namespace ComplianceChecker.AutoCAD
{
    /// <summary>
    /// The Compliance palette (P11.4): what failed first, each with clause, measured / required and
    /// what to change; can't-verify next; passes only on request. Clicking a row zooms to it.
    /// </summary>
    internal static class ResultsPalette
    {
        // Always light, whatever AutoCAD's theme: the web app's light tokens.
        private static readonly Brush Paper = Brush(0xff, 0xff, 0xff);
        private static readonly Brush Ink = Brush(0x0a, 0x0a, 0x0b);
        private static readonly Brush Muted = Brush(0x5c, 0x5c, 0x61);
        private static readonly Brush Bad = Brush(0xd4, 0x24, 0x3d);
        private static readonly Brush Good = Brush(0x12, 0x87, 0x5a);
        private static readonly Brush Picked = Brush(0xf0, 0xf0, 0xf1);

        private static Brush Brush(byte r, byte g, byte b)
        {
            var brush = new SolidColorBrush(Color.FromRgb(r, g, b));
            brush.Freeze();
            return brush;
        }

        private static PaletteSet? _set;
        private static readonly TextBlock StatusLine = new() { TextWrapping = TextWrapping.Wrap, Margin = new Thickness(0, 6, 0, 6), Foreground = Muted };
        private static readonly TextBlock Summary = new() { FontSize = 15, FontWeight = FontWeights.SemiBold, TextWrapping = TextWrapping.Wrap };
        private static readonly StackPanel ListPanel = new();
        private static readonly CheckBox Passes = new() { Content = "show passes", Margin = new Thickness(0, 4, 0, 8) };
        private static CheckReport? _report;
        private static Button? _picked;
        private static string? _projectId;

        public static void SetStatus(string text)
        {
            try
            {
                Ensure();
                StatusLine.Text = text;
                _set!.Visible = true;
            }
            catch (Exception e)
            {
                Log.Error("palette status", e);
            }
        }

        public static void ShowReport(Document doc, CheckReport report, string projectId)
        {
            _report = report;
            _projectId = projectId;
            try
            {
                Ensure();
                StatusLine.Text = $"Checked {DateTime.Now:HH:mm} · {report.Results.Count(r => r.Status != Status.NotApplicable)} clauses";
                Render();
                _set!.Visible = true;
            }
            catch (Exception e)
            {
                Log.Error("palette report", e);
                doc.Editor.WriteMessage($"\nCompliance: couldn't show the palette ({e.Message}); details in {Log.FilePath}");
            }
        }

        public static void Toggle()
        {
            try
            {
                Ensure();
                if (_report is not null)
                    Render();
                _set!.Visible = true;
            }
            catch (Exception e)
            {
                Log.Error("palette toggle", e);
            }
        }

        private static void Ensure()
        {
            if (_set is not null)
                return;
            var buttons = new WrapPanel { Margin = new Thickness(0, 8, 0, 0) };
            buttons.Children.Add(Icons.Button(Icons.Refresh, "Re-check", (_, _) => Run("CCCHECK")));
            buttons.Children.Add(Icons.Button(Icons.Pin, "Site", (_, _) => Run("CCSITE")));
            buttons.Children.Add(Icons.Button(Icons.Book, "Report", (_, _) => Run("CCREPORT")));

            var root = new DockPanel { Margin = new Thickness(0), Background = Paper };
            TextElement.SetForeground(root, Ink);
            var head = new StackPanel { Margin = new Thickness(10, 10, 10, 0) };
            head.Children.Add(Summary);
            head.Children.Add(StatusLine);
            head.Children.Add(Passes);
            head.Children.Add(buttons);
            DockPanel.SetDock(head, Dock.Top);
            root.Children.Add(head);
            root.Children.Add(new ScrollViewer { Content = ListPanel, VerticalScrollBarVisibility = ScrollBarVisibility.Auto, Margin = new Thickness(10, 8, 10, 10), Background = Paper });
            Passes.Foreground = Ink;
            Passes.Checked += (_, _) => Render();
            Passes.Unchecked += (_, _) => Render();
            Summary.Text = "Not checked yet";

            _set = new PaletteSet("Compliance", new Guid("6f1c2a0e-3b1d-4b7e-9a43-6a2f4c1d7e21"))
            {
                MinimumSize = new System.Drawing.Size(300, 300),
                Style = PaletteSetStyles.ShowCloseButton | PaletteSetStyles.ShowAutoHideButton | PaletteSetStyles.ShowPropertiesMenu,
            };
            _set.AddVisual("Results", root);
            _set.KeepFocus = false;
            _set.Visible = true;
            try
            {
                _set.Dock = DockSides.Right;
            }
            catch (Exception e)
            {
                Log.Error("palette dock", e); // floating is fine too
            }
            Log.Info("palette created");
        }

        private static void Render()
        {
            ListPanel.Children.Clear();
            if (_report is null)
                return;
            var view = new ReportView(_report);
            var s = _report.Summary;
            Summary.Text = s.Fail == 0 ? "No issues to fix" : $"{s.Fail} issue{(s.Fail == 1 ? "" : "s")} to fix";
            Summary.Foreground = s.Fail == 0 ? Good : Bad;
            foreach (ResultGroup g in view.Groups)
            {
                if (g.Status is Status.NotApplicable || (g.Status == Status.Pass && Passes.IsChecked != true))
                    continue;
                ListPanel.Children.Add(new TextBlock
                {
                    Text = $"{g.Title} ({g.Rows.Count})",
                    FontWeight = FontWeights.SemiBold,
                    Margin = new Thickness(0, 10, 0, 4),
                });
                foreach (ResultRow r in g.Rows)
                    ListPanel.Children.Add(Row(r));
            }
        }

        private static FrameworkElement Row(ResultRow r)
        {
            (string icon, Brush brush) = r.Status switch
            {
                Status.Fail => (Icons.Cross, Bad),
                Status.Pass => (Icons.Check, Good),
                _ => (Icons.Question, Muted),
            };
            var text = new StackPanel { Margin = new Thickness(8, 0, 0, 0) };
            text.Children.Add(new TextBlock { Text = r.Title, TextWrapping = TextWrapping.Wrap });
            string where = r.ElementKind is null ? "whole building" : $"{r.ElementKind} {r.ElementId}";
            text.Children.Add(new TextBlock { Text = $"{r.ClauseRef} · {where}", Foreground = Muted, FontSize = 11, TextWrapping = TextWrapping.Wrap });
            if (r.Measured is not null || r.Limit is not null)
                text.Children.Add(new TextBlock
                {
                    Text = $"{r.Measured ?? "—"} / {r.Limit ?? "—"}" + (r.Fix is null ? "" : $"   {r.Fix}"),
                    FontFamily = new FontFamily("Consolas"),
                    Foreground = r.Status == Status.Fail ? Bad : Muted,
                });
            if (r.Status == Status.Unverifiable && r.MissingInputs.Count > 0)
                text.Children.Add(new TextBlock { Text = "needs: " + string.Join(", ", r.MissingInputs), Foreground = Muted, FontSize = 11, TextWrapping = TextWrapping.Wrap });

            var line = new DockPanel { Margin = new Thickness(0, 3, 0, 3) };
            var glyph = Icons.Glyph(icon, 14, brush);
            glyph.VerticalAlignment = VerticalAlignment.Top;
            DockPanel.SetDock(glyph, Dock.Left);
            line.Children.Add(glyph);
            line.Children.Add(text);
            var button = new Button
            {
                Content = line,
                HorizontalContentAlignment = HorizontalAlignment.Stretch,
                Background = Paper,
                Foreground = Ink,
                BorderThickness = new Thickness(0),
                Padding = new Thickness(4),
                Cursor = System.Windows.Input.Cursors.Hand,
                ToolTip = r.Message + "\nClick to show it on the drawing.",
            };
            button.Click += (_, _) =>
            {
                if (_picked is not null)
                    _picked.Background = Paper;
                button.Background = Picked;
                _picked = button;
                if (AcApp.DocumentManager.MdiActiveDocument is { } doc)
                {
                    try
                    {
                        Highlighter.Focus(doc, r);
                    }
                    catch (Exception e)
                    {
                        Log.Error("focus", e);
                    }
                }
            };
            return button;
        }

        private static void Run(string command) =>
            AcApp.DocumentManager.MdiActiveDocument?.SendStringToExecute("_" + command + " ", true, false, true);

        public static string? ProjectId => _projectId;
        public static CheckReport? Report => _report;
    }
}
