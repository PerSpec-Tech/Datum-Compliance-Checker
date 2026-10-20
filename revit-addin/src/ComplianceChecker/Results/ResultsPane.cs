using System.Collections.Generic;
using System.Diagnostics;
using System.Linq;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Documents;
using System.Windows.Media;
using System.Windows.Shapes;
using Autodesk.Revit.DB;
using Autodesk.Revit.UI;
using ComplianceChecker.Core.Results;
using ComplianceChecker.Generated;
using Color = System.Windows.Media.Color;
using Ellipse = System.Windows.Shapes.Ellipse;
using Grid = System.Windows.Controls.Grid;
using Rectangle = System.Windows.Shapes.Rectangle;

namespace ComplianceChecker.Results
{
    /// <summary>
    /// Dockable results pane (P5.7): summary, FSI headroom, what's missing (questions), results grouped
    /// by status with NEW / FIXED markers (P5.9), and a detail panel citing the clause. Clicking
    /// "Select in model" selects the element by UniqueId and zooms to it.
    /// </summary>
    public sealed class ResultsPane : IDockablePaneProvider
    {
        private readonly Page _page = new() { Background = Brushes.White };
        private readonly StackPanel _header = new() { Margin = new Thickness(10, 8, 10, 4) };
        private readonly StackPanel _body = new() { Margin = new Thickness(6, 0, 6, 6) };
        private readonly StackPanel _detail = new() { Margin = new Thickness(10) };
        private UiActionQueue? _ui;
        private ListBox? _selectedList;

        public ResultsPane()
        {
            var detailBorder = new Border
            {
                BorderBrush = Brushes.LightGray,
                BorderThickness = new Thickness(0, 1, 0, 0),
                Height = 280,
                Child = new ScrollViewer { VerticalScrollBarVisibility = ScrollBarVisibility.Auto, Content = _detail },
            };
            var dock = new DockPanel();
            DockPanel.SetDock(_header, Dock.Top);
            DockPanel.SetDock(detailBorder, Dock.Bottom);
            dock.Children.Add(_header);
            dock.Children.Add(detailBorder);
            dock.Children.Add(new ScrollViewer { VerticalScrollBarVisibility = ScrollBarVisibility.Auto, Content = _body });
            _page.Content = dock;
            _header.Children.Add(new TextBlock { Text = "Run a check (Compliance › Run Check) to see results here.", TextWrapping = TextWrapping.Wrap });
        }

        public void Attach(UiActionQueue ui) => _ui = ui;

        public void SetupDockablePane(DockablePaneProviderData data)
        {
            data.FrameworkElement = _page;
            data.InitialState = new DockablePaneState { DockPosition = DockPosition.Right };
        }

        /// <summary>Main thread only.</summary>
        public void Show(ReportView view, IReadOnlyList<string> warnings)
        {
            _header.Children.Clear();
            _body.Children.Clear();
            _detail.Children.Clear();
            _selectedList = null;

            _header.Children.Add(new TextBlock { Text = view.SummaryLine, FontWeight = FontWeights.SemiBold, FontSize = 14, TextWrapping = TextWrapping.Wrap });
            if (view.FsiLine is not null)
                _header.Children.Add(Muted(view.FsiLine));
            if (view.DiffLine is not null)
                _header.Children.Add(new TextBlock { Text = view.DiffLine, Foreground = Brushes.RoyalBlue, Margin = new Thickness(0, 2, 0, 0) });
            if (warnings.Count > 0)
                _header.Children.Add(new Expander
                {
                    Header = $"Export warnings ({warnings.Count})",
                    Content = new TextBlock { Text = "• " + string.Join("\n• ", warnings), TextWrapping = TextWrapping.Wrap, Foreground = Brushes.DarkGoldenrod },
                });

            if (view.Questions.Count > 0)
                _body.Children.Add(QuestionsBlock(view.Questions));
            foreach (ResultGroup g in view.Groups)
                _body.Children.Add(GroupBlock(g));
            _detail.Children.Add(Muted("Select a result to see the clause, the values and how to fix it."));
        }

        private UIElement QuestionsBlock(IReadOnlyList<Question> questions)
        {
            var list = new StackPanel { Margin = new Thickness(4) };
            foreach (Question q in questions.Take(8))
                list.Children.Add(new TextBlock
                {
                    Text = $"• {q.Prompt}  (unlocks {q.Unlocks} check{(q.Unlocks == 1 ? "" : "s")})",
                    TextWrapping = TextWrapping.Wrap,
                    Margin = new Thickness(0, 2, 0, 2),
                });
            var open = new Button { Content = "Answer in Site Setup…", HorizontalAlignment = HorizontalAlignment.Left, Padding = new Thickness(8, 2, 8, 2), Margin = new Thickness(0, 6, 0, 0) };
            open.Click += (_, _) => _ui?.Post(app =>
            {
                RevitCommandId? id = RevitCommandId.LookupCommandId("CustomCtrl_%CustomCtrl_%Compliance%Bylaw check%cc_site");
                if (id is not null)
                    app.PostCommand(id);
                else
                    TaskDialog.Show("Compliance Checker", "Open Compliance › Site Setup to answer these.");
            });
            list.Children.Add(open);
            return new Expander { Header = Header($"What's missing ({questions.Count})", Brushes.DarkOrange), IsExpanded = true, Content = list, Margin = new Thickness(0, 4, 0, 4) };
        }

        private UIElement GroupBlock(ResultGroup g)
        {
            var list = new ListBox { BorderThickness = new Thickness(0) };
            foreach (ResultRow row in g.Rows)
                list.Items.Add(new ListBoxItem { Content = RowContent(row), Tag = row });
            list.SelectionChanged += (_, _) =>
            {
                if (list.SelectedItem is ListBoxItem { Tag: ResultRow row })
                {
                    if (_selectedList is not null && _selectedList != list)
                        _selectedList.SelectedIndex = -1;
                    _selectedList = list;
                    ShowDetail(row);
                }
            };
            bool open = g.Status is Status.Fail or Status.Unverifiable or Status.Advisory;
            return new Expander { Header = Header($"{g.Title} ({g.Rows.Count})", StatusBrush(g.Status)), IsExpanded = open, Content = list, Margin = new Thickness(0, 4, 0, 4) };
        }

        private static UIElement RowContent(ResultRow r)
        {
            var p = new StackPanel { Orientation = Orientation.Horizontal };
            p.Children.Add(new Ellipse { Width = 9, Height = 9, Fill = StatusBrush(r.Status), Margin = new Thickness(0, 0, 6, 0), VerticalAlignment = VerticalAlignment.Center });
            p.Children.Add(new TextBlock { Text = r.Title });
            if (r.ElementId is not null)
                p.Children.Add(new TextBlock { Text = $"  · {r.ElementId}", Foreground = Brushes.Gray });
            if (r.Fix is not null)
                p.Children.Add(new TextBlock { Text = $"  — {r.Fix}", Foreground = Brushes.Firebrick });
            if (r.Change != Change.None)
                p.Children.Add(Badge(r.Change == Change.New ? "NEW" : "FIXED", r.Change == Change.New ? Brushes.Firebrick : Brushes.SeaGreen));
            return p;
        }

        private void ShowDetail(ResultRow r)
        {
            _detail.Children.Clear();
            _detail.Children.Add(new TextBlock { Text = r.Title, FontWeight = FontWeights.SemiBold, FontSize = 13, TextWrapping = TextWrapping.Wrap });
            _detail.Children.Add(new TextBlock { Text = r.Message, TextWrapping = TextWrapping.Wrap, Margin = new Thickness(0, 4, 0, 4) });
            if (r.Fix is not null)
                _detail.Children.Add(new TextBlock { Text = r.Fix, FontWeight = FontWeights.SemiBold, Foreground = Brushes.Firebrick });
            if (r.Measured is not null || r.Limit is not null)
                _detail.Children.Add(Muted($"Measured {r.Measured ?? "?"} · limit {r.Limit ?? "?"}"));

            _detail.Children.Add(new TextBlock { Text = $"Clause {r.ClauseRef} — {r.ClauseSource}", FontWeight = FontWeights.SemiBold, Margin = new Thickness(0, 8, 0, 2), TextWrapping = TextWrapping.Wrap });
            _detail.Children.Add(new TextBlock { Text = "“" + r.ClauseExcerpt + "”", FontStyle = FontStyles.Italic, TextWrapping = TextWrapping.Wrap });

            if (r.MissingInputs.Count > 0)
                _detail.Children.Add(new TextBlock { Text = "Needs: " + string.Join(", ", r.MissingInputs), Foreground = Brushes.DarkOrange, TextWrapping = TextWrapping.Wrap, Margin = new Thickness(0, 6, 0, 0) });
            if (r.Facts.Count > 0)
            {
                _detail.Children.Add(new TextBlock { Text = "Facts used", FontWeight = FontWeights.SemiBold, Margin = new Thickness(0, 8, 0, 2) });
                foreach (string f in r.Facts)
                    _detail.Children.Add(Muted("• " + f));
            }
            if (r.IsDraftRule)
                _detail.Children.Add(Badge("Draft rule — not yet verified by a person", Brushes.DarkGoldenrod));
            if (r.PossiblySuperseded)
            {
                var link = new Hyperlink(new Run("This clause may have been amended — see source")) { NavigateUri = r.FreshnessUrl is null ? null : new System.Uri(r.FreshnessUrl) };
                link.RequestNavigate += (_, e) => Process.Start(new ProcessStartInfo(e.Uri.AbsoluteUri) { UseShellExecute = true });
                _detail.Children.Add(new TextBlock(link) { Margin = new Thickness(0, 6, 0, 0), TextWrapping = TextWrapping.Wrap });
            }
            if (r.SourceId is not null)
            {
                var select = new Button { Content = "Select in model", HorizontalAlignment = HorizontalAlignment.Left, Padding = new Thickness(8, 2, 8, 2), Margin = new Thickness(0, 10, 0, 0) };
                string uid = r.SourceId;
                select.Click += (_, _) => _ui?.Post(app => SelectElement(app, uid));
                _detail.Children.Add(select);
            }
        }

        private static void SelectElement(UIApplication app, string uniqueId)
        {
            UIDocument? uidoc = app.ActiveUIDocument;
            if (uidoc?.Document.GetElement(uniqueId) is not Element e)
            {
                TaskDialog.Show("Compliance Checker", "That element is no longer in the model. Run the check again.");
                return;
            }
            uidoc.Selection.SetElementIds(new List<ElementId> { e.Id });
            uidoc.ShowElements(e.Id);
        }

        // ------------------------------------------------------------------ styling

        private static UIElement Header(string text, Brush colour)
        {
            var p = new StackPanel { Orientation = Orientation.Horizontal };
            p.Children.Add(new Rectangle { Width = 4, Height = 14, Fill = colour, Margin = new Thickness(0, 0, 6, 0) });
            p.Children.Add(new TextBlock { Text = text, FontWeight = FontWeights.SemiBold });
            return p;
        }

        private static Border Badge(string text, Brush colour) => new()
        {
            Background = colour,
            CornerRadius = new CornerRadius(3),
            Padding = new Thickness(5, 0, 5, 0),
            Margin = new Thickness(6, 4, 0, 0),
            HorizontalAlignment = HorizontalAlignment.Left,
            Child = new TextBlock { Text = text, Foreground = Brushes.White, FontSize = 10, FontWeight = FontWeights.SemiBold },
        };

        private static TextBlock Muted(string text) => new() { Text = text, Foreground = Brushes.DimGray, TextWrapping = TextWrapping.Wrap, Margin = new Thickness(0, 2, 0, 0) };

        private static Brush StatusBrush(Status s) => new SolidColorBrush(s switch
        {
            Status.Fail => Color.FromRgb(220, 38, 38),
            Status.Unverifiable => Color.FromRgb(245, 158, 11),
            Status.Advisory => Color.FromRgb(99, 102, 241),
            Status.Pass => Color.FromRgb(22, 163, 74),
            _ => Color.FromRgb(156, 163, 175),
        });
    }
}
