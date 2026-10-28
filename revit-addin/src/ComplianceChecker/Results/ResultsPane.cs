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
using ComplianceChecker.Core.Live;
using ComplianceChecker.Core.Results;
using ComplianceChecker.Generated;
using Color = System.Windows.Media.Color;
using Ellipse = System.Windows.Shapes.Ellipse;
using Grid = System.Windows.Controls.Grid;
using Rectangle = System.Windows.Shapes.Rectangle;
using Visibility = System.Windows.Visibility;

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

        // Live strip (P9.2/P9.3): one calm line at the top, plus the lens toggle. Hidden until a check
        // has produced a live pack for the open model.
        private readonly Border _live = new()
        {
            Background = new SolidColorBrush(Color.FromRgb(20, 20, 22)),
            Padding = new Thickness(10, 6, 10, 6),
            Visibility = Visibility.Collapsed,
        };
        private readonly TextBlock _liveText = new()
        {
            Foreground = new SolidColorBrush(Color.FromRgb(242, 242, 243)),
            FontFamily = new FontFamily("Consolas"),
            FontSize = 11.5,
            TextWrapping = TextWrapping.Wrap,
        };
        private readonly TextBlock _liveDetail = new()
        {
            Foreground = new SolidColorBrush(Color.FromRgb(154, 154, 161)),
            FontSize = 11,
            TextWrapping = TextWrapping.Wrap,
            Margin = new Thickness(0, 3, 0, 0),
        };
        private readonly System.Windows.Controls.Primitives.ToggleButton _lensButton = new()
        {
            Content = "lens",
            ToolTip = "Show the buildable line and setback issues over the current view (changes nothing in the model)",
            Padding = new Thickness(8, 1, 8, 1),
            Margin = new Thickness(8, 0, 0, 0),
            VerticalAlignment = VerticalAlignment.Top,
        };

        /// <summary>Raised when the user turns the lens on or off.</summary>
        public event System.Action<bool>? LensToggled;

        public ResultsPane()
        {
            var liveRow = new DockPanel();
            DockPanel.SetDock(_lensButton, Dock.Right);
            liveRow.Children.Add(_lensButton);
            var liveStack = new StackPanel();
            liveStack.Children.Add(new TextBlock
            {
                Text = "LIVE PREVIEW",
                Foreground = new SolidColorBrush(Color.FromRgb(122, 122, 128)),
                FontSize = 9.5,
                Margin = new Thickness(0, 0, 0, 2),
            });
            liveStack.Children.Add(_liveText);
            liveStack.Children.Add(_liveDetail);
            liveRow.Children.Add(liveStack);
            _live.Child = liveRow;
            _lensButton.Checked += (_, _) => LensToggled?.Invoke(true);
            _lensButton.Unchecked += (_, _) => LensToggled?.Invoke(false);

            var detailBorder = new Border
            {
                BorderBrush = Brushes.LightGray,
                BorderThickness = new Thickness(0, 1, 0, 0),
                Height = 280,
                Child = new ScrollViewer { VerticalScrollBarVisibility = ScrollBarVisibility.Auto, Content = _detail },
            };
            var dock = new DockPanel();
            DockPanel.SetDock(_live, Dock.Top);
            DockPanel.SetDock(_header, Dock.Top);
            DockPanel.SetDock(detailBorder, Dock.Bottom);
            dock.Children.Add(_live);
            dock.Children.Add(_header);
            dock.Children.Add(detailBorder);
            dock.Children.Add(new ScrollViewer { VerticalScrollBarVisibility = ScrollBarVisibility.Auto, Content = _body });
            _page.Content = dock;
            _header.Children.Add(new TextBlock { Text = "Run a check (Datum › Run Check) to see results here.", TextWrapping = TextWrapping.Wrap });
        }

        public void Attach(UiActionQueue ui) => _ui = ui;

        /// <summary>Main thread. The live engine's latest result, as one quiet line and a short list.</summary>
        public void ShowLive(LiveStatus status, bool lensOn)
        {
            _live.Visibility = Visibility.Visible;
            _liveText.Text = status.StripText();
            var lines = status.Setbacks
                .GroupBy(s => s.ElementId)
                .Select(g => g.OrderByDescending(s => s.DeficitM).First())
                .OrderByDescending(s => s.DeficitM)
                .Take(3)
                .Select(s => $"{s.Label}: {s.DistanceM:0.00} m from side {s.EdgeId}, needs {s.RequiredM:0.00} ({s.ClauseRef})")
                .Concat(status.Thresholds.Take(3).Select(t => $"{t.Title}: {t.Value:0.00} vs {t.Limit:0.00} ({t.ClauseRef})"))
                .ToList();
            int more = status.IssueCount - lines.Count;
            _liveDetail.Text = lines.Count == 0
                ? "Within the setbacks and size limits the last check found. Run Check for the full report."
                : string.Join("\n", lines) + (more > 0 ? $"\n+{more} more" : "");
            if (_lensButton.IsChecked != lensOn)
                _lensButton.IsChecked = lensOn;
        }

        /// <summary>Main thread. Keep the toggle in step when the ribbon command switches the lens.</summary>
        public void SetLensChecked(bool on)
        {
            if (_lensButton.IsChecked != on)
                _lensButton.IsChecked = on;
        }

        /// <summary>Main thread. Live mode couldn't read the model this time; it tries again on the next edit.</summary>
        public void ShowLiveError(string message)
        {
            _live.Visibility = Visibility.Visible;
            _liveDetail.Text = "Live preview paused: " + message;
        }

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
                    TaskDialog.Show("Datum", "Open Datum › Site Setup to answer these.");
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
                TaskDialog.Show("Datum", "That element is no longer in the model. Run the check again.");
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
