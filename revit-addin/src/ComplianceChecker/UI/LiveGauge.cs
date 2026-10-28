using System;
using System.Linq;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using System.Windows.Shapes;
using ComplianceChecker.Core.Live;

namespace ComplianceChecker.UI
{
    /// <summary>
    /// The live panel (shared by the Revit and AutoCAD plug-ins), docked on the left while you model:
    /// a vertical FSI bar that rises with the built-up area (ticks at the base and maximum FSI, red past
    /// the maximum), the height against its limit, and the setbacks. Past the maximum FSI a red notice
    /// says by how much. Preview only: the full check stays the official result.
    /// </summary>
    public sealed class LiveGauge : Border
    {
        private static readonly Brush Ink = Rgb(10, 10, 11), Ink2 = Rgb(92, 92, 97), Ink3 = Rgb(117, 117, 122);
        private static readonly Brush Line = Rgb(212, 212, 215), Surface = Rgb(245, 245, 246), Danger = Rgb(212, 36, 61);
        private static readonly Brush Accent = Rgb(210, 43, 16);
        private static readonly FontFamily Ui = new("DM Sans, Segoe UI");
        private static readonly FontFamily Mono = new("JetBrains Mono, Consolas");
        private const double BarH = 300, BarW = 30;

        private readonly Canvas _bar = new() { Width = BarW + 64, Height = BarH };
        private readonly TextBlock _fsi = Text(40, Ink, mono: true, bold: true);
        private readonly TextBlock _fsiOf = Text(13, Ink2);
        private readonly TextBlock _fsiLeft = Text(13, Ink2, mono: true);
        private readonly TextBlock _height = Text(15, Ink, mono: true);
        private readonly TextBlock _heightOf = Text(12, Ink3);
        private readonly TextBlock _margins = Text(15, Ink);
        private readonly TextBlock _marginsList = Text(12, Ink2);
        private readonly Border _alert = new()
        {
            BorderBrush = Danger, BorderThickness = new Thickness(1.5), CornerRadius = new CornerRadius(2),
            Padding = new Thickness(10, 8, 10, 8), Margin = new Thickness(0, 14, 0, 0), Visibility = Visibility.Collapsed,
        };
        private readonly TextBlock _alertText = Text(13, Danger);

        public LiveGauge()
        {
            Background = Brushes.White;
            Padding = new Thickness(16, 14, 16, 14);
            var root = new StackPanel();

            var head = new TextBlock { FontFamily = Ui, FontSize = 17, FontWeight = FontWeights.SemiBold, Foreground = Ink };
            head.Inlines.Add(new System.Windows.Documents.Run("datum"));
            head.Inlines.Add(new System.Windows.Documents.Run(".") { Foreground = Accent });
            head.Inlines.Add(new System.Windows.Documents.Run("  live") { FontFamily = Mono, FontSize = 11, FontWeight = FontWeights.Normal, Foreground = Ink3 });
            root.Children.Add(head);

            var fsiRow = new Grid { Margin = new Thickness(0, 16, 0, 0) };
            fsiRow.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
            fsiRow.ColumnDefinitions.Add(new ColumnDefinition());
            fsiRow.Children.Add(_bar);
            var fsiText = new StackPanel { Margin = new Thickness(6, 0, 0, 0), VerticalAlignment = VerticalAlignment.Top };
            fsiText.Children.Add(Text(11, Ink3, mono: true, text: "FSI"));
            fsiText.Children.Add(_fsi);
            fsiText.Children.Add(_fsiOf);
            fsiText.Children.Add(_fsiLeft);
            Grid.SetColumn(fsiText, 1);
            fsiRow.Children.Add(fsiText);
            root.Children.Add(fsiRow);

            _alertText.FontWeight = FontWeights.SemiBold;
            _alert.Child = _alertText;
            root.Children.Add(_alert);

            root.Children.Add(Rule());
            root.Children.Add(Text(11, Ink3, mono: true, text: "HEIGHT"));
            root.Children.Add(_height);
            root.Children.Add(_heightOf);
            root.Children.Add(Rule());
            root.Children.Add(Text(11, Ink3, mono: true, text: "SETBACKS"));
            root.Children.Add(_margins);
            root.Children.Add(_marginsList);
            root.Children.Add(Rule());
            root.Children.Add(Text(11, Ink3, text: "Preview while you model. Run Check for the full, official report."));

            Child = new ScrollViewer { VerticalScrollBarVisibility = ScrollBarVisibility.Auto, Content = root };
            ShowMessage("Run a check to start the live preview.");
        }

        /// <summary>Before the first check, or when the preview is paused.</summary>
        public void ShowMessage(string message)
        {
            _fsi.Text = "–";
            _fsiOf.Text = message;
            _fsiLeft.Text = "";
            _height.Text = "–";
            _heightOf.Text = "";
            _margins.Text = "–";
            _marginsList.Text = "";
            _alert.Visibility = Visibility.Collapsed;
            DrawBar(null, null, null);
        }

        public void Show(LiveStatus s)
        {
            _fsi.Text = s.Fsi is double f ? f.ToString("0.00") : "–";
            _fsi.Foreground = s.FsiOver ? Danger : Ink;
            _fsiOf.Text = s.FsiMax is double fm ? $"of {fm:0.00} max" : "maximum not known yet";
            _fsiLeft.Text = s.FsiLeftM2 is double l ? (l >= 0 ? $"{l:0} m² left" : $"{-l:0} m² over") : "";
            _fsiLeft.Foreground = s.FsiOver ? Danger : Ink2;
            DrawBar(s.Fsi, s.FsiBaseM2 is double b && s.FsiMaxM2 is double m && m > 0 && s.FsiMax is double mx ? b / m * mx : null, s.FsiMax);

            _alert.Visibility = s.FsiOver || s.HeightOver ? Visibility.Visible : Visibility.Collapsed;
            _alertText.Text = string.Join("\n", new[]
            {
                s.FsiOver ? $"✕ FSI exceeded: {-s.FsiLeftM2!.Value:0} m² over the maximum built-up area." : null,
                s.HeightOver ? $"✕ Height {s.HeightM:0.0} m is over the {s.HeightLimitM:0.0} m limit{(s.HeightClauseRef is { } c ? $" ({c})" : "")}." : null,
            }.Where(x => x is not null));

            _height.Text = s.HeightM is double h ? $"{h:0.0} m" : "–";
            _height.Foreground = s.HeightOver ? Danger : Ink;
            _heightOf.Text = s.HeightLimitM is double lim
                ? $"limit {lim:0.0} m{(s.HeightClauseRef is { } cr ? $" · UDCPR {cr}" : "")}"
                : "no height limit on this road";

            var worst = s.Setbacks.GroupBy(x => x.ElementId).Select(g => g.OrderByDescending(x => x.DeficitM).First())
                .OrderByDescending(x => x.DeficitM).ToList();
            _margins.Text = worst.Count == 0 ? "✓ inside the buildable line" : $"✕ {worst.Count} past the buildable line";
            _margins.Foreground = worst.Count == 0 ? Ink : Danger;
            _marginsList.Text = string.Join("\n", worst.Take(4).Select(x =>
                $"{x.Label}: {x.DeficitM:0.00} m too close to side {x.EdgeId}{(x.ClauseRef is { } c ? $" ({c})" : "")}"));
        }

        /// <summary>The vertical bar: fill to the FSI now, ticks at base and max, red above the max.</summary>
        private void DrawBar(double? fsi, double? baseFsi, double? max)
        {
            _bar.Children.Clear();
            Add(new Rectangle { Width = BarW, Height = BarH, Fill = Surface, Stroke = Line, StrokeThickness = 1 }, 0, 0);
            if (max is not double mx || mx <= 0)
                return;
            double top = Math.Max(mx * 1.2, fsi ?? 0);
            double Y(double v) => BarH - Math.Min(v, top) / top * BarH;
            if (fsi is double f && f > 0)
            {
                double within = Math.Min(f, mx);
                Add(new Rectangle { Width = BarW - 2, Height = BarH - Y(within), Fill = Ink }, 1, Y(within));
                if (f > mx)
                    Add(new Rectangle { Width = BarW - 2, Height = Y(mx) - Y(f), Fill = Danger }, 1, Y(f));
            }
            Tick(Y(mx), $"max {mx:0.00}", Ink);
            if (baseFsi is double b && b > 0 && Math.Abs(b - mx) > 0.01)
                Tick(Y(b), $"base {b:0.00}", Ink3);
        }

        private void Tick(double y, string label, Brush brush)
        {
            Add(new Line { X1 = 0, X2 = BarW + 6, Y1 = y, Y2 = y, Stroke = brush, StrokeThickness = 1.5 }, 0, 0);
            Add(Text(10.5, brush, mono: true, text: label), BarW + 8, y - 8);
        }

        private void Add(UIElement e, double x, double y)
        {
            Canvas.SetLeft(e, x);
            Canvas.SetTop(e, y);
            _bar.Children.Add(e);
        }

        private static Border Rule() => new() { Height = 1, Background = Line, Margin = new Thickness(0, 14, 0, 10) };

        private static TextBlock Text(double size, Brush brush, bool mono = false, bool bold = false, string text = "") => new()
        {
            Text = text, FontSize = size, Foreground = brush, FontFamily = mono ? Mono : Ui,
            FontWeight = bold ? FontWeights.SemiBold : FontWeights.Normal, TextWrapping = TextWrapping.Wrap,
        };

        private static SolidColorBrush Rgb(byte r, byte g, byte b)
        {
            var brush = new SolidColorBrush(Color.FromRgb(r, g, b));
            brush.Freeze();
            return brush;
        }
    }
}
