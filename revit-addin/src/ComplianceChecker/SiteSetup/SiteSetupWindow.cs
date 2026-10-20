using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using System.Windows.Shapes;
using ComplianceChecker.Core.Model;
using Geometry = ComplianceChecker.Core.Model.Geometry;
using WpfLine = System.Windows.Shapes.Line;

namespace ComplianceChecker.SiteSetup
{
    /// <summary>
    /// Site Setup (P5.4): tag each plot edge (road / neighbour / open space, road width, basis) on a small
    /// plan, and declare the legal facts the model can't give (D5). Edits a copy of the <see cref="Brief"/>;
    /// the caller saves it only if the user clicks Save.
    /// </summary>
    internal sealed class SiteSetupWindow : Window
    {
        private static readonly (string Value, string Label)[] Kinds =
            { ("", "— not set —"), ("road", "Road"), ("neighbour", "Neighbouring plot"), ("open_space", "Open space") };
        private static readonly (string Value, string Label)[] Bases =
            { ("", "— not set —"), ("development_plan", "Development Plan width"), ("existing", "Existing width") };
        private static readonly (string Value, string Label)[] Groups =
        {
            ("", "— not set —"), ("A", "A — Residential"), ("B", "B — Educational"), ("C", "C — Institutional"),
            ("D", "D — Assembly"), ("E", "E — Business"), ("F", "F — Mercantile"), ("G", "G — Industrial"),
            ("H", "H — Storage"), ("J", "J — Hazardous"),
        };
        private static readonly (string Value, string Label)[] BuildingTypes =
        {
            ("", "— not set —"), ("bungalow_self_use", "Bungalow / independent house (self use)"),
            ("standalone", "Standalone building"), ("group_housing", "Group housing"),
            ("mixed_use", "Mixed use (residential + commercial)"), ("other", "Other"),
        };
        private static readonly (string Key, string Label)[] SpecialFlags =
        {
            ("heritage", "Heritage building / precinct"), ("coastal", "Coastal regulation zone"),
            ("airport_zone", "Airport height-restriction zone"), ("ht_line", "Under / near high-tension lines"),
            ("railway", "Near a railway line"), ("river_flood_line", "Within river blue / red flood lines"),
            ("hill_slope_bdp", "Hill-top / hill-slope / Biodiversity Park zone"),
            ("defence_vicinity", "Near defence land"), ("metro_rail_within_20m", "Within 20 m of a metro rail line"),
        };

        private readonly Brief _brief;
        private readonly List<(string Key, Pt A, Pt B)> _edges = new();
        private readonly List<Pt>? _footprint;
        private readonly double? _measuredPlotArea;

        private readonly Canvas _plan = new() { Width = 360, Height = 300, Background = Brushes.White, ClipToBounds = true };
        private readonly ListBox _edgeList = new() { Height = 130 };
        private readonly ComboBox _kind = Combo(Kinds);
        private readonly TextBox _width = new();
        private readonly ComboBox _basis = Combo(Bases);
        private readonly StackPanel _edgeEditor = new() { IsEnabled = false };
        private readonly TextBlock _status = new() { Foreground = Brushes.Firebrick, TextWrapping = TextWrapping.Wrap };
        private readonly Dictionary<string, Control> _fields = new();
        private bool _loadingEdge;

        public SiteSetupWindow(Brief brief, RawModel site)
        {
            _brief = Brief.FromJson(brief.ToJson()); // edit a copy
            Result = _brief;
            Title = "Compliance Checker — Site Setup";
            Width = 900;
            Height = 700;
            WindowStartupLocation = WindowStartupLocation.CenterScreen;

            List<Pt>? boundary = Geometry.ChainLoop(site.PropertyLineSegments);
            if (boundary is not null)
            {
                for (int i = 0; i < boundary.Count; i++)
                {
                    Pt a = boundary[i], b = boundary[(i + 1) % boundary.Count];
                    _edges.Add((Geometry.EdgeKey(a, b), a, b));
                }
                _measuredPlotArea = Geometry.Area(boundary);
            }
            _footprint = site.Footprint is { Count: >= 3 } fp ? Geometry.Normalise(fp) : null;

            var root = new Grid { Margin = new Thickness(12) };
            root.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(380) });
            root.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
            root.RowDefinitions.Add(new RowDefinition { Height = new GridLength(1, GridUnitType.Star) });
            root.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });

            var left = BuildSitePanel(boundary is not null, site.PropertyLineSegments.Count);
            Grid.SetColumn(left, 0);
            root.Children.Add(left);

            var right = new ScrollViewer { VerticalScrollBarVisibility = ScrollBarVisibility.Auto, Content = BuildFactsPanel(site), Margin = new Thickness(12, 0, 0, 0) };
            Grid.SetColumn(right, 1);
            root.Children.Add(right);

            var footer = new DockPanel { Margin = new Thickness(0, 10, 0, 0) };
            var save = new Button { Content = "Save", Width = 100, IsDefault = true };
            var cancel = new Button { Content = "Cancel", Width = 100, IsCancel = true, Margin = new Thickness(8, 0, 0, 0) };
            var buttons = new StackPanel { Orientation = Orientation.Horizontal };
            buttons.Children.Add(save);
            buttons.Children.Add(cancel);
            DockPanel.SetDock(buttons, Dock.Right);
            footer.Children.Add(buttons);
            footer.Children.Add(_status);
            Grid.SetRow(footer, 1);
            Grid.SetColumnSpan(footer, 2);
            root.Children.Add(footer);
            Content = root;

            save.Click += (_, _) => Save();
            DrawPlan();
        }

        /// <summary>The edited brief (valid only when ShowDialog returned true).</summary>
        public Brief Result { get; private set; }

        /// <summary>True when the user asked to draw property lines (the caller posts Revit's command).</summary>
        public bool DrawPropertyLinesRequested { get; private set; }

        // ------------------------------------------------------------------ left: plan + edges

        private UIElement BuildSitePanel(bool hasBoundary, int segments)
        {
            var panel = new StackPanel();
            panel.Children.Add(Heading("Plot edges"));
            if (!hasBoundary)
            {
                panel.Children.Add(new TextBlock
                {
                    TextWrapping = TextWrapping.Wrap,
                    Margin = new Thickness(0, 0, 0, 8),
                    Text = segments == 0
                        ? "This model has no property lines, so margins and FSI can't be checked."
                        : "The property lines don't form one closed loop. Fix them so the plot boundary can be read.",
                });
                var draw = new Button { Content = "Draw property lines in Revit…", HorizontalAlignment = HorizontalAlignment.Left, Padding = new Thickness(8, 2, 8, 2) };
                draw.Click += (_, _) =>
                {
                    DrawPropertyLinesRequested = true;
                    DialogResult = false;
                };
                panel.Children.Add(draw);
                return panel;
            }

            panel.Children.Add(new Border { BorderBrush = Brushes.LightGray, BorderThickness = new Thickness(1), Child = _plan, HorizontalAlignment = HorizontalAlignment.Left });
            panel.Children.Add(new TextBlock { Text = "Click an edge on the plan or in the list. Blue = road, grey = neighbour, green = open space, orange = not tagged.", TextWrapping = TextWrapping.Wrap, FontSize = 11, Foreground = Brushes.DimGray, Margin = new Thickness(0, 4, 0, 6) });

            for (int i = 0; i < _edges.Count; i++)
                _edgeList.Items.Add(EdgeLabel(i));
            _edgeList.SelectionChanged += (_, _) => LoadEdge();
            panel.Children.Add(_edgeList);

            _edgeEditor.Margin = new Thickness(0, 8, 0, 0);
            _edgeEditor.Children.Add(Labelled("This edge faces", _kind));
            _edgeEditor.Children.Add(Labelled("Road width (m)", _width));
            _edgeEditor.Children.Add(Labelled("Width as per", _basis));
            _kind.SelectionChanged += (_, _) => StoreEdge();
            _basis.SelectionChanged += (_, _) => StoreEdge();
            _width.TextChanged += (_, _) => StoreEdge();
            panel.Children.Add(_edgeEditor);
            return panel;
        }

        private string EdgeLabel(int i)
        {
            var (key, a, b) = _edges[i];
            _brief.Edges.TryGetValue(key, out EdgeTag? tag);
            string what = tag?.Kind switch
            {
                "road" => $"road {tag.RoadWidthM?.ToString("0.##", CultureInfo.InvariantCulture) ?? "?"} m",
                "neighbour" => "neighbour",
                "open_space" => "open space",
                _ => "not tagged",
            };
            return $"e{i + 1}  ({Geometry.Dist(a, b):0.0} m)  —  {what}";
        }

        private void LoadEdge()
        {
            int i = _edgeList.SelectedIndex;
            _edgeEditor.IsEnabled = i >= 0;
            if (i < 0)
                return;
            _loadingEdge = true;
            _brief.Edges.TryGetValue(_edges[i].Key, out EdgeTag? tag);
            Select(_kind, Kinds, tag?.Kind);
            _width.Text = tag?.RoadWidthM?.ToString(CultureInfo.InvariantCulture) ?? "";
            Select(_basis, Bases, tag?.Basis);
            _loadingEdge = false;
            DrawPlan();
        }

        private void StoreEdge()
        {
            int i = _edgeList.SelectedIndex;
            if (_loadingEdge || i < 0)
                return;
            string? kind = Value(_kind, Kinds);
            double? width = double.TryParse(_width.Text.Trim(), NumberStyles.Float, CultureInfo.InvariantCulture, out double w) ? w : null;
            string? basis = Value(_basis, Bases);
            if (kind is null && width is null && basis is null)
                _brief.Edges.Remove(_edges[i].Key);
            else
                _brief.Edges[_edges[i].Key] = new EdgeTag { Kind = kind, RoadWidthM = kind == "road" ? width : null, Basis = kind == "road" ? basis : null };
            _width.IsEnabled = _basis.IsEnabled = kind == "road";
            _edgeList.Items[i] = EdgeLabel(i);
            _edgeList.SelectedIndex = i;
            DrawPlan();
        }

        private void DrawPlan()
        {
            _plan.Children.Clear();
            if (_edges.Count == 0)
                return;
            var pts = _edges.SelectMany(e => new[] { e.A, e.B }).Concat(_footprint ?? new List<Pt>()).ToList();
            double minX = pts.Min(p => p.X), maxX = pts.Max(p => p.X), minY = pts.Min(p => p.Y), maxY = pts.Max(p => p.Y);
            double scale = Math.Min((_plan.Width - 40) / Math.Max(maxX - minX, 1e-6), (_plan.Height - 40) / Math.Max(maxY - minY, 1e-6));
            Point Map(Pt p) => new(20 + (p.X - minX) * scale, _plan.Height - 20 - (p.Y - minY) * scale); // flip Y

            if (_footprint is not null)
            {
                var poly = new Polygon { Fill = new SolidColorBrush(Color.FromRgb(225, 230, 240)), Stroke = Brushes.SlateGray, StrokeThickness = 1 };
                foreach (Pt p in _footprint)
                    poly.Points.Add(Map(p));
                _plan.Children.Add(poly);
            }
            for (int i = 0; i < _edges.Count; i++)
            {
                var (key, a, b) = _edges[i];
                _brief.Edges.TryGetValue(key, out EdgeTag? tag);
                bool selected = i == _edgeList.SelectedIndex;
                Brush colour = selected ? Brushes.Red : tag?.Kind switch
                {
                    "road" => Brushes.RoyalBlue,
                    "neighbour" => Brushes.Gray,
                    "open_space" => Brushes.SeaGreen,
                    _ => Brushes.DarkOrange,
                };
                Point pa = Map(a), pb = Map(b);
                var line = new WpfLine
                {
                    X1 = pa.X, Y1 = pa.Y, X2 = pb.X, Y2 = pb.Y, Stroke = colour,
                    StrokeThickness = selected ? 6 : tag?.Kind == "road" ? 5 : 3,
                    StrokeDashArray = tag?.Kind is null && !selected ? new DoubleCollection { 2, 1 } : null,
                    Cursor = System.Windows.Input.Cursors.Hand, Tag = i,
                };
                line.MouseLeftButtonDown += (s, _) => _edgeList.SelectedIndex = (int)((WpfLine)s).Tag;
                _plan.Children.Add(line);
                var label = new TextBlock { Text = $"e{i + 1}", FontSize = 11, Foreground = colour, Background = Brushes.White };
                Canvas.SetLeft(label, (pa.X + pb.X) / 2 - 8);
                Canvas.SetTop(label, (pa.Y + pb.Y) / 2 - 8);
                _plan.Children.Add(label);
            }
        }

        // ------------------------------------------------------------------ right: declared facts

        private UIElement BuildFactsPanel(RawModel site)
        {
            var p = new StackPanel();
            p.Children.Add(Heading("Location"));
            bool fromRevit = _brief.Latitude is null && site.Latitude is not null;
            Field(p, "lat", "Latitude (°)", Text((_brief.Latitude ?? site.Latitude)?.ToString("0.######", CultureInfo.InvariantCulture)));
            Field(p, "lon", "Longitude (°)", Text((_brief.Longitude ?? site.Longitude)?.ToString("0.######", CultureInfo.InvariantCulture)));
            if (fromRevit)
                p.Children.Add(Hint("Taken from Revit's project location — check it. Templates often default to another city."));

            p.Children.Add(Heading("Building"));
            Field(p, "group", "Occupancy group (NBC Part 4)", Combo(Groups, _brief.OccupancyGroup));
            Field(p, "subdivision", "Sub-division, e.g. A-4", Text(_brief.OccupancySubdivision));
            Field(p, "building_type", "Building type", Combo(BuildingTypes, _brief.BuildingType));

            p.Children.Add(Heading("Plot (as per documents and the Development Plan)"));
            Field(p, "plot_area", "Plot area as per documents (sq.m)", Text(_brief.PlotAreaM2?.ToString(CultureInfo.InvariantCulture)));
            if (_measuredPlotArea is double m)
                p.Children.Add(Hint($"Measured from property lines: {m:0.0} sq.m (documents may differ)."));
            var zone = new ComboBox { IsEditable = true, Text = _brief.Zone ?? "" };
            foreach (string z in new[] { "residential", "commercial", "industrial", "public_semi_public", "agricultural" })
                zone.Items.Add(z);
            Field(p, "zone", "Development Plan zone", zone);
            Field(p, "congested", "In a congested area / Gaothan?", TriState(_brief.CongestedArea));
            Field(p, "corner", "Corner plot?", TriState(_brief.IsCornerPlot));

            p.Children.Add(Heading("Metro TOD (UDCPR 14.2.1)"));
            Field(p, "tod", "Inside the notified TOD zone?", TriState(_brief.MetroTod));
            p.Children.Add(Hint("Leave as Unknown to let the server work it out from the nearest metro station."));
            Field(p, "tod_share", "Share of plot inside the TOD zone (0–1)", Text(_brief.PlotShareInTod?.ToString(CultureInfo.InvariantCulture)));

            p.Children.Add(Heading("Other site conditions"));
            foreach (var (key, label) in SpecialFlags)
                Field(p, "special:" + key, label, TriState(_brief.Special.TryGetValue(key, out bool v) ? v : null));
            return p;
        }

        private void Save()
        {
            _status.Text = "";
            double? lat = Num("lat"), lon = Num("lon"), plot = Num("plot_area"), share = Num("tod_share");
            if (lat is { } la && (la < -90 || la > 90) || lon is { } lo && (lo < -180 || lo > 180))
            {
                _status.Text = "Latitude must be −90…90 and longitude −180…180.";
                return;
            }
            if (share is { } s && (s < 0 || s > 1))
            {
                _status.Text = "TOD share must be between 0 and 1.";
                return;
            }
            var badRoad = _edges.Select((e, i) => (e, i)).FirstOrDefault(x =>
                _brief.Edges.TryGetValue(x.e.Key, out EdgeTag? t) && t.Kind == "road" && (t.RoadWidthM is null or <= 0));
            if (badRoad.e.Key is not null)
            {
                _status.Text = $"Edge e{badRoad.i + 1} is a road: enter its width in metres.";
                return;
            }

            _brief.Latitude = lat;
            _brief.Longitude = lon;
            _brief.OccupancyGroup = Value((ComboBox)_fields["group"], Groups);
            _brief.OccupancySubdivision = Str("subdivision");
            _brief.BuildingType = Value((ComboBox)_fields["building_type"], BuildingTypes);
            _brief.PlotAreaM2 = plot;
            _brief.Zone = string.IsNullOrWhiteSpace(((ComboBox)_fields["zone"]).Text) ? null : ((ComboBox)_fields["zone"]).Text.Trim();
            _brief.CongestedArea = Tri("congested");
            _brief.IsCornerPlot = Tri("corner");
            _brief.MetroTod = Tri("tod");
            _brief.PlotShareInTod = share;
            foreach (var (key, _) in SpecialFlags)
            {
                bool? v = Tri("special:" + key);
                if (v is null)
                    _brief.Special.Remove(key);
                else
                    _brief.Special[key] = v.Value;
            }
            // Edge tags for edges that no longer exist (property lines moved) are dropped.
            var current = _edges.Select(e => e.Key).ToHashSet();
            foreach (string stale in _brief.Edges.Keys.Where(k => !current.Contains(k)).ToList())
                _brief.Edges.Remove(stale);

            Result = _brief;
            DialogResult = true;
        }

        // ------------------------------------------------------------------ small helpers

        private void Field(Panel p, string key, string label, Control control)
        {
            _fields[key] = control;
            p.Children.Add(Labelled(label, control));
        }

        private static UIElement Labelled(string label, Control control)
        {
            var g = new Grid { Margin = new Thickness(0, 3, 0, 3) };
            g.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(230) });
            g.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
            var t = new TextBlock { Text = label, VerticalAlignment = VerticalAlignment.Center, TextWrapping = TextWrapping.Wrap };
            g.Children.Add(t);
            Grid.SetColumn(control, 1);
            g.Children.Add(control);
            return g;
        }

        private static TextBlock Heading(string text) =>
            new() { Text = text, FontWeight = FontWeights.SemiBold, FontSize = 14, Margin = new Thickness(0, 12, 0, 4) };

        private static TextBlock Hint(string text) =>
            new() { Text = text, FontSize = 11, Foreground = Brushes.DimGray, TextWrapping = TextWrapping.Wrap, Margin = new Thickness(230, 0, 0, 4) };

        private static TextBox Text(string? value) => new() { Text = value ?? "" };

        private static ComboBox Combo((string Value, string Label)[] items, string? selected = null)
        {
            var c = new ComboBox();
            foreach (var (_, label) in items)
                c.Items.Add(label);
            Select(c, items, selected);
            return c;
        }

        private static void Select(ComboBox c, (string Value, string Label)[] items, string? value) =>
            c.SelectedIndex = Math.Max(0, Array.FindIndex(items, i => i.Value == (value ?? "")));

        private static string? Value(ComboBox c, (string Value, string Label)[] items) =>
            c.SelectedIndex > 0 ? items[c.SelectedIndex].Value : null;

        private static ComboBox TriState(bool? value)
        {
            var c = new ComboBox();
            c.Items.Add("Unknown");
            c.Items.Add("Yes");
            c.Items.Add("No");
            c.SelectedIndex = value is null ? 0 : value.Value ? 1 : 2;
            return c;
        }

        private bool? Tri(string key) => ((ComboBox)_fields[key]).SelectedIndex switch { 1 => true, 2 => false, _ => null };

        private string? Str(string key) => string.IsNullOrWhiteSpace(((TextBox)_fields[key]).Text) ? null : ((TextBox)_fields[key]).Text.Trim();

        private double? Num(string key) =>
            double.TryParse(((TextBox)_fields[key]).Text.Trim(), NumberStyles.Float, CultureInfo.InvariantCulture, out double v) ? v : null;
    }
}
