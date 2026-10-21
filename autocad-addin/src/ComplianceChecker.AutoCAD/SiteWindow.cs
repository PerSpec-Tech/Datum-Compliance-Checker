using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Text.Json;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Documents;
using System.Windows.Media;
using ComplianceChecker.Core.Api;

namespace ComplianceChecker.AutoCAD
{
    /// <summary>The site dialog (white, like the palette). Picks on the drawing close it for a moment.</summary>
    internal sealed class SiteWindow : Window
    {
        private static readonly Brush Paper = Brushes.White;
        private static readonly Brush Ink = new SolidColorBrush(Color.FromRgb(0x0a, 0x0a, 0x0b));
        private static readonly Brush Muted = new SolidColorBrush(Color.FromRgb(0x5c, 0x5c, 0x61));
        private static readonly Brush Line = new SolidColorBrush(Color.FromRgb(0xe5, 0xe5, 0xe7));

        private static readonly (string Label, object Value)[] BuildingTypes =
        {
            ("bungalow (own use)", "bungalow_self_use"), ("apartments", "standalone"), ("group housing", "group_housing"),
            ("mixed use", "mixed_use"), ("other", "other"),
        };
        private static readonly (string Label, object Value)[] Occupancies =
        {
            ("A-2 · 1–2 family dwelling", new Dictionary<string, object?> { ["group"] = "A", ["subdivision"] = "A-2" }),
            ("A-4 · apartment houses", new Dictionary<string, object?> { ["group"] = "A", ["subdivision"] = "A-4" }),
            ("E · business", new Dictionary<string, object?> { ["group"] = "E", ["subdivision"] = null }),
            ("F · mercantile", new Dictionary<string, object?> { ["group"] = "F", ["subdivision"] = null }),
        };
        private static readonly (string Label, object Value)[] YesNo = { ("congested area", true), ("not congested", false) };

        private readonly ApiClient _api;
        private readonly string _projectId;
        private readonly SiteState _s;
        private readonly TextBlock _location = new() { TextWrapping = TextWrapping.Wrap };
        private readonly TextBox _query = new() { MinWidth = 260, Padding = new Thickness(4, 3, 4, 3) };
        private readonly ListBox _places = new() { MaxHeight = 120, Visibility = Visibility.Collapsed, Margin = new Thickness(0, 6, 0, 0) };
        private readonly StackPanel _facts = new();
        private readonly TextBlock _status = new() { Foreground = Muted, TextWrapping = TextWrapping.Wrap };

        public SiteAction Action { get; private set; } = SiteAction.Cancel;

        public SiteWindow(ApiClient api, string projectId, SiteState state)
        {
            _api = api;
            _projectId = projectId;
            _s = state;
            Title = "Compliance Checker — Site";
            Width = 560;
            Height = 720;
            Background = Paper;
            WindowStartupLocation = WindowStartupLocation.CenterScreen;
            TextElement.SetForeground(this, Ink);

            var body = new StackPanel { Margin = new Thickness(18, 14, 18, 14) };
            body.Children.Add(Heading("Location"));
            body.Children.Add(_location);
            var search = new DockPanel { Margin = new Thickness(0, 8, 0, 0) };
            var go = Icons.Button(Icons.Pin, "Find", async (_, _) => await SearchAsync());
            go.IsDefault = true;
            DockPanel.SetDock(go, Dock.Right);
            search.Children.Add(go);
            search.Children.Add(_query);
            body.Children.Add(search);
            body.Children.Add(Hint("Street, area or landmark in Pune; or “18.5165, 73.8420”. AutoCAD’s own location (GEOGRAPHICLOCATION) is used when the drawing has one."));
            body.Children.Add(_places);
            _places.SelectionChanged += async (_, _) =>
            {
                if (_places.SelectedItem is ListBoxItem { Tag: Place p })
                    await SetLocationAsync(p.Lat, p.Lon, p.Label);
            };

            body.Children.Add(Heading("Plot"));
            body.Children.Add(new TextBlock { Text = state.PlotNote, TextWrapping = TextWrapping.Wrap });
            body.Children.Add(Row(Icons.Button(Icons.Layers, "Pick plot boundary…", (_, _) => Close(SiteAction.PickPlot))));

            body.Children.Add(Heading("Sides"));
            if (state.Sides.Count == 0)
                body.Children.Add(Hint("Set the plot first."));
            foreach (SideInfo side in state.Sides)
                body.Children.Add(SideRow(side));
            body.Children.Add(Row(Icons.Button(Icons.Pin, "Pick a road side on the drawing…", (_, _) => Close(SiteAction.PickRoad))));
            body.Children.Add(Hint("The sides are labelled e1, e2… in cyan on the drawing while this window is open."));

            body.Children.Add(Heading("Planning facts"));
            body.Children.Add(_facts);
            body.Children.Add(Hint("Suggested from the rooms and the location; pick a value to confirm it. Unconfirmed suggestions are still used, marked as inferred."));

            var save = Icons.Button(Icons.Check, "Save and check", (_, _) => Close(SiteAction.Save));
            var web = Icons.Button(Icons.Book, "Map in browser", (_, _) => Close(SiteAction.Browser));
            var cancel = Icons.Button(Icons.Cross, "Cancel", (_, _) => Close(SiteAction.Cancel));
            cancel.IsCancel = true;
            var footer = new DockPanel { Margin = new Thickness(18, 10, 18, 14), LastChildFill = false };
            DockPanel.SetDock(_status, Dock.Left);
            footer.Children.Add(_status);
            foreach (Button b in new[] { cancel, web, save })
            {
                DockPanel.SetDock(b, Dock.Right);
                footer.Children.Add(b);
            }

            var root = new DockPanel();
            DockPanel.SetDock(footer, Dock.Bottom);
            root.Children.Add(footer);
            root.Children.Add(new Border { BorderBrush = Line, BorderThickness = new Thickness(0, 0, 0, 1), Child = new ScrollViewer { Content = body, VerticalScrollBarVisibility = ScrollBarVisibility.Auto } });
            Content = root;

            ShowLocation();
            Loaded += async (_, _) =>
            {
                if (_s.Lat is { } lat && _s.Lon is { } lon)
                {
                    await DescribeAsync(lat, lon);
                    await LoadFactsAsync(lat, lon);
                }
                else
                {
                    _query.Focus();
                }
            };
        }

        private void Close(SiteAction action)
        {
            Action = action;
            DialogResult = action is not SiteAction.Cancel;
        }

        // ------------------------------------------------------------------ location

        private async Task SearchAsync()
        {
            string q = _query.Text.Trim();
            var m = System.Text.RegularExpressions.Regex.Match(q, @"^\s*(-?\d+(?:\.\d+)?)\s*[, ]\s*(-?\d+(?:\.\d+)?)\s*$");
            if (m.Success)
            {
                await SetLocationAsync(double.Parse(m.Groups[1].Value, CultureInfo.InvariantCulture),
                                       double.Parse(m.Groups[2].Value, CultureInfo.InvariantCulture), null);
                return;
            }
            if (q.Length < 3)
                return;
            _status.Text = "Searching…";
            try
            {
                IReadOnlyList<Place> places = await _api.GeocodeAsync(q);
                _places.Items.Clear();
                foreach (Place p in places)
                    _places.Items.Add(new ListBoxItem { Content = p.Label, Tag = p });
                _places.Visibility = places.Count > 0 ? Visibility.Visible : Visibility.Collapsed;
                _status.Text = places.Count == 0 ? "No match in Pune." : "";
                if (places.Count == 1)
                    await SetLocationAsync(places[0].Lat, places[0].Lon, places[0].Label);
            }
            catch (Exception e)
            {
                _status.Text = "Search failed: " + e.Message;
            }
        }

        private async Task SetLocationAsync(double lat, double lon, string? label)
        {
            _s.Lat = lat;
            _s.Lon = lon;
            _s.LocationNote = label;
            _s.LocationChanged = true;
            ShowLocation();
            await DescribeAsync(lat, lon);
            await LoadFactsAsync(lat, lon);
        }

        private void ShowLocation() =>
            _location.Text = _s.Lat is { } lat && _s.Lon is { } lon
                ? string.Create(CultureInfo.InvariantCulture, $"{lat:0.00000}° N, {lon:0.00000}° E") + (_s.LocationNote is { } n ? $"  ·  {n}" : "")
                : "Not set yet.";

        private async Task DescribeAsync(double lat, double lon)
        {
            try
            {
                Located l = await _api.LocateAsync(lat, lon);
                _location.Text = (l.Label ?? "pinned") + string.Create(CultureInfo.InvariantCulture, $"  ({lat:0.00000}, {lon:0.00000})")
                                 + (l.AuthorityId == "pmc" ? "  ·  Pune Municipal Corporation" : $"  ·  {l.Note}");
            }
            catch (Exception e)
            {
                Log.Error("locate", e);
            }
        }

        // ------------------------------------------------------------------ sides

        private FrameworkElement SideRow(SideInfo side)
        {
            double len = side.A.GetDistanceTo(side.B) * MetresPerUnit;
            var kind = new ComboBox { Width = 120, ItemsSource = new[] { "—", "road", "neighbour", "open_space" } };
            var width = new TextBox { Width = 50, Margin = new Thickness(6, 0, 0, 0), Padding = new Thickness(3, 1, 3, 1) };
            _s.Tags.TryGetValue(side.Id, out var tag);
            kind.SelectedItem = tag.Kind ?? "—";
            width.Text = tag.Width?.ToString("0.##", CultureInfo.InvariantCulture) ?? "";
            width.IsEnabled = tag.Kind == "road";
            void Store()
            {
                string k = kind.SelectedItem as string ?? "—";
                width.IsEnabled = k == "road";
                if (k == "—")
                    _s.Tags.Remove(side.Id);
                else
                    _s.Tags[side.Id] = (k, k == "road" && double.TryParse(width.Text, NumberStyles.Float, CultureInfo.InvariantCulture, out double w) ? w : null);
            }
            kind.SelectionChanged += (_, _) => Store();
            width.TextChanged += (_, _) => Store();

            var row = new DockPanel { Margin = new Thickness(0, 3, 0, 3) };
            var right = new StackPanel { Orientation = Orientation.Horizontal };
            right.Children.Add(kind);
            right.Children.Add(width);
            right.Children.Add(new TextBlock { Text = " m", VerticalAlignment = VerticalAlignment.Center, Foreground = Muted });
            DockPanel.SetDock(right, Dock.Right);
            row.Children.Add(right);
            row.Children.Add(new TextBlock { Text = string.Create(CultureInfo.InvariantCulture, $"{side.Id}  ·  {len:0.0} m"), VerticalAlignment = VerticalAlignment.Center, FontFamily = new FontFamily("Consolas") });
            return row;
        }

        private double MetresPerUnit => Markup.MetresPerUnit(Autodesk.AutoCAD.ApplicationServices.Application.DocumentManager.MdiActiveDocument.Database);

        // ------------------------------------------------------------------ planning facts

        private async Task LoadFactsAsync(double lat, double lon)
        {
            _facts.Children.Clear();
            _facts.Children.Add(Hint("Looking up the area and reading the rooms… (land use can take up to a minute)"));
            try
            {
                IReadOnlyList<Suggestion> list = await _api.GetSuggestionsAsync(_projectId, lat, lon);
                _facts.Children.Clear();
                foreach (Suggestion s in list)
                    _facts.Children.Add(FactRow(s));
            }
            catch (Exception e)
            {
                _facts.Children.Clear();
                _facts.Children.Add(Hint("Couldn't load suggestions: " + e.Message));
            }
        }

        private FrameworkElement FactRow(Suggestion s)
        {
            string source = s.Current.TryGetProperty("source", out var src) ? src.GetString() ?? "" : "";
            bool fixedFact = source is "model" or "declared";
            JsonElement fact = fixedFact ? s.Current : s.Suggested;
            JsonElement value = fact.TryGetProperty("value", out var v) ? v : default;
            string label = s.Path switch
            {
                "project.building_type" => "type",
                "project.occupancy" => "occupancy",
                "project.congested_area" => "area",
                "project.zone" => "land use",
                _ => s.Path,
            };
            (string Label, object Value)[]? options = s.Path switch
            {
                "project.building_type" => BuildingTypes,
                "project.occupancy" => Occupancies,
                "project.congested_area" => YesNo,
                _ => null,
            };

            var row = new DockPanel { Margin = new Thickness(0, 4, 0, 4) };
            row.Children.Add(new TextBlock { Text = label, Width = 90, Foreground = Muted, VerticalAlignment = VerticalAlignment.Top });
            DockPanel.SetDock(row.Children[0], Dock.Left);
            var right = new StackPanel();
            if (options is not null && !fixedFact)
            {
                var combo = new ComboBox { Width = 230, HorizontalAlignment = HorizontalAlignment.Left };
                foreach (var o in options)
                    combo.Items.Add(new ComboBoxItem { Content = o.Label, Tag = o.Value });
                string current = value.ValueKind == JsonValueKind.Undefined ? "" : value.GetRawText();
                combo.SelectedItem = combo.Items.Cast<ComboBoxItem>().FirstOrDefault(i => JsonSerializer.Serialize(i.Tag) == current);
                combo.SelectionChanged += (_, _) =>
                {
                    if (combo.SelectedItem is ComboBoxItem { Tag: { } t })
                        _s.Facts[s.Path] = t;
                };
                var line = new StackPanel { Orientation = Orientation.Horizontal };
                line.Children.Add(combo);
                var confirm = Icons.Button(Icons.Check, "confirm", (_, _) =>
                {
                    if (combo.SelectedItem is ComboBoxItem { Tag: { } t })
                        _s.Facts[s.Path] = t;
                });
                confirm.Margin = new Thickness(6, 0, 0, 0);
                line.Children.Add(confirm);
                right.Children.Add(line);
            }
            else
            {
                string text = value.ValueKind switch
                {
                    JsonValueKind.String => value.GetString()!.Replace('_', ' '),
                    JsonValueKind.True => "yes",
                    JsonValueKind.False => "no",
                    JsonValueKind.Object when value.TryGetProperty("subdivision", out var sd) && sd.ValueKind == JsonValueKind.String => sd.GetString()!,
                    JsonValueKind.Object when value.TryGetProperty("group", out var g) => g.GetString()!,
                    _ => "—",
                };
                right.Children.Add(new TextBlock { Text = text + (fixedFact ? $"  ({(source == "model" ? "from the model" : "yours")})" : "  (suggested)") });
                if (!fixedFact && value.ValueKind != JsonValueKind.Undefined)
                    right.Children.Add(Row(Icons.Button(Icons.Check, "confirm", (_, _) => _s.Facts[s.Path] = JsonSerializer.Deserialize<object>(value.GetRawText()))));
            }
            if (!fixedFact && fact.TryGetProperty("note", out var note) && note.ValueKind == JsonValueKind.String)
                right.Children.Add(Hint(note.GetString()!));
            row.Children.Add(right);
            return row;
        }

        // ------------------------------------------------------------------ small parts

        private static TextBlock Heading(string text) =>
            new() { Text = text, FontWeight = FontWeights.SemiBold, FontSize = 14, Margin = new Thickness(0, 14, 0, 6) };

        private static TextBlock Hint(string text) =>
            new() { Text = text, Foreground = Muted, FontSize = 11, TextWrapping = TextWrapping.Wrap, Margin = new Thickness(0, 4, 0, 0) };

        private static FrameworkElement Row(UIElement child)
        {
            var p = new StackPanel { Orientation = Orientation.Horizontal, Margin = new Thickness(0, 6, 0, 0) };
            p.Children.Add(child);
            return p;
        }
    }
}
