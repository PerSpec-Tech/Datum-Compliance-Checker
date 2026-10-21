using System;
using System.Linq;
using System.Windows;
using System.Windows.Controls;
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
        private static PaletteSet? _set;
        private static readonly TextBlock StatusLine = new() { TextWrapping = TextWrapping.Wrap, Margin = new Thickness(0, 6, 0, 6), Foreground = Icons.Grey };
        private static readonly TextBlock Summary = new() { FontSize = 15, FontWeight = FontWeights.SemiBold, TextWrapping = TextWrapping.Wrap };
        private static readonly StackPanel ListPanel = new();
        private static readonly CheckBox Passes = new() { Content = "show passes", Margin = new Thickness(0, 4, 0, 8) };
        private static CheckReport? _report;
        private static string? _projectId;

        public static void SetStatus(string text)
        {
            Ensure();
            StatusLine.Text = text;
            _set!.Visible = true;
        }

        public static void ShowReport(Document doc, CheckReport report, string projectId)
        {
            Ensure();
            _report = report;
            _projectId = projectId;
            StatusLine.Text = $"Checked {DateTime.Now:HH:mm} · {report.Results.Count(r => r.Status != Status.NotApplicable)} clauses";
            Render();
            _set!.Visible = true;
        }

        public static void Toggle()
        {
            Ensure();
            _set!.Visible = true;
        }

        private static void Ensure()
        {
            if (_set is not null)
                return;
            var buttons = new WrapPanel { Margin = new Thickness(0, 8, 0, 0) };
            buttons.Children.Add(Icons.Button(Icons.Refresh, "Re-check", (_, _) => Run("CCCHECK")));
            buttons.Children.Add(Icons.Button(Icons.Pin, "Site", (_, _) => Run("CCSITE")));
            buttons.Children.Add(Icons.Button(Icons.Book, "Report", (_, _) => Run("CCREPORT")));

            var root = new DockPanel { Margin = new Thickness(10) };
            var head = new StackPanel();
            head.Children.Add(Summary);
            head.Children.Add(StatusLine);
            head.Children.Add(Passes);
            head.Children.Add(buttons);
            DockPanel.SetDock(head, Dock.Top);
            root.Children.Add(head);
            root.Children.Add(new ScrollViewer { Content = ListPanel, VerticalScrollBarVisibility = ScrollBarVisibility.Auto, Margin = new Thickness(0, 8, 0, 0) });
            Passes.Checked += (_, _) => Render();
            Passes.Unchecked += (_, _) => Render();
            Summary.Text = "Not checked yet";

            _set = new PaletteSet("Compliance", new Guid("6f1c2a0e-3b1d-4b7e-9a43-6a2f4c1d7e21"))
            {
                MinimumSize = new System.Drawing.Size(300, 300),
                Style = PaletteSetStyles.ShowCloseButton | PaletteSetStyles.ShowAutoHideButton | PaletteSetStyles.ShowPropertiesMenu,
            };
            _set.AddVisual("Results", root);
            _set.Dock = DockSides.Right;
        }

        private static void Render()
        {
            ListPanel.Children.Clear();
            if (_report is null)
                return;
            var view = new ReportView(_report);
            var s = _report.Summary;
            Summary.Text = s.Fail == 0 ? "No issues to fix" : $"{s.Fail} issue{(s.Fail == 1 ? "" : "s")} to fix";
            Summary.Foreground = s.Fail == 0 ? Icons.Green : Icons.Red;
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
                Status.Fail => (Icons.Cross, Icons.Red),
                Status.Pass => (Icons.Check, Icons.Green),
                _ => (Icons.Question, Icons.Grey),
            };
            var text = new StackPanel { Margin = new Thickness(8, 0, 0, 0) };
            text.Children.Add(new TextBlock { Text = r.Title, TextWrapping = TextWrapping.Wrap });
            string where = r.ElementKind is null ? "whole building" : $"{r.ElementKind} {r.ElementId}";
            text.Children.Add(new TextBlock { Text = $"{r.ClauseRef} · {where}", Foreground = Icons.Grey, FontSize = 11, TextWrapping = TextWrapping.Wrap });
            if (r.Measured is not null || r.Limit is not null)
                text.Children.Add(new TextBlock
                {
                    Text = $"{r.Measured ?? "—"} / {r.Limit ?? "—"}" + (r.Fix is null ? "" : $"   {r.Fix}"),
                    FontFamily = new FontFamily("Consolas"),
                    Foreground = r.Status == Status.Fail ? Icons.Red : Icons.Grey,
                });
            if (r.Status == Status.Unverifiable && r.MissingInputs.Count > 0)
                text.Children.Add(new TextBlock { Text = "needs: " + string.Join(", ", r.MissingInputs), Foreground = Icons.Grey, FontSize = 11, TextWrapping = TextWrapping.Wrap });

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
                Background = Brushes.Transparent,
                BorderThickness = new Thickness(0),
                Padding = new Thickness(4),
                Cursor = System.Windows.Input.Cursors.Hand,
                ToolTip = r.SourceId is null ? r.Message : r.Message + "\nClick to zoom to it.",
            };
            if (r.SourceId is { } handle)
                button.Click += (_, _) =>
                {
                    if (AcApp.DocumentManager.MdiActiveDocument is { } doc)
                        Highlighter.ZoomTo(doc, handle);
                };
            return button;
        }

        private static void Run(string command) =>
            AcApp.DocumentManager.MdiActiveDocument?.SendStringToExecute("_" + command + " ", true, false, true);

        public static string? ProjectId => _projectId;
        public static CheckReport? Report => _report;
    }
}
