using System;
using System.Collections.Generic;
using System.Linq;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Controls;
using ComplianceChecker.Core.Api;

namespace ComplianceChecker.AutoCAD
{
    /// <summary>
    /// Layer setup (P11.2): what each layer is. PreDCR layers are recognised by name; the rest are
    /// suggested by Nemotron from the layer's name and contents (marked "suggested") or chosen here.
    /// The choices are stored with the project on the server, the same table as in the web app.
    /// </summary>
    internal sealed class LayersWindow : Window
    {
        // Same roles as the server and the web app (web/src/api/client.ts LAYER_ROLES).
        private static readonly string[] Roles =
        {
            "plot", "road", "footprint", "floor", "floor_height", "ground", "fsi_resi", "fsi_comm",
            "fsi_other", "carpet", "room", "door", "window", "stair", "balcony", "parking", "ignore",
        };

        private readonly ApiClient _api;
        private readonly string _projectId;
        private readonly Dictionary<string, ComboBox> _choices = new();
        private readonly TextBlock _status = new() { TextWrapping = TextWrapping.Wrap, Margin = new Thickness(0, 8, 0, 0) };

        public DrawingUpload? Result { get; private set; }

        public LayersWindow(ApiClient api, string projectId, DrawingUpload upload)
        {
            _api = api;
            _projectId = projectId;
            Title = "Compliance Checker — Layers";
            Width = 520;
            Height = 560;
            WindowStartupLocation = WindowStartupLocation.CenterScreen;

            var rows = new StackPanel();
            foreach (LayerRole l in (upload.Layers ?? []).OrderBy(l => l.Role is null ? 0 : l.Source == "suggested" ? 1 : 2).ThenBy(l => l.Layer))
            {
                var combo = new ComboBox { Width = 150, ItemsSource = new[] { "—" }.Concat(Roles).ToList(), SelectedItem = l.Role ?? "—" };
                _choices[l.Layer] = combo;
                string note = l.Source switch
                {
                    "predcr" => "PreDCR",
                    "user" => "yours",
                    "suggested" => $"suggested {(l.Confidence is { } c ? $"{c:P0}" : "")}",
                    "convention" => "drawing only",
                    _ => "unknown",
                };
                var line = new DockPanel { Margin = new Thickness(0, 2, 0, 2) };
                DockPanel.SetDock(combo, Dock.Right);
                line.Children.Add(combo);
                var label = new StackPanel();
                label.Children.Add(new TextBlock { Text = l.Layer, FontWeight = l.Role is null ? FontWeights.SemiBold : FontWeights.Normal });
                label.Children.Add(new TextBlock { Text = $"{l.Entities} entities · {note}", Foreground = Icons.Grey, FontSize = 11 });
                line.Children.Add(label);
                rows.Children.Add(line);
            }

            var save = Icons.Button(Icons.Check, "Confirm and check", async (_, _) => await SaveAsync());
            save.IsDefault = true;
            var cancel = Icons.Button(Icons.Cross, "Cancel", (_, _) => DialogResult = false);
            cancel.IsCancel = true;
            var buttons = new StackPanel { Orientation = Orientation.Horizontal, HorizontalAlignment = HorizontalAlignment.Right, Margin = new Thickness(0, 10, 0, 0) };
            buttons.Children.Add(save);
            buttons.Children.Add(cancel);

            var head = new TextBlock
            {
                Text = upload.Unmapped > 0
                    ? $"{upload.Unmapped} layer{(upload.Unmapped == 1 ? "" : "s")} not understood yet. Say what each is, or “ignore”."
                    : "Some layers were guessed from their name and contents. Check them, then confirm.",
                TextWrapping = TextWrapping.Wrap,
                Margin = new Thickness(0, 0, 0, 10),
            };
            var root = new DockPanel { Margin = new Thickness(14) };
            DockPanel.SetDock(head, Dock.Top);
            DockPanel.SetDock(buttons, Dock.Bottom);
            DockPanel.SetDock(_status, Dock.Bottom);
            root.Children.Add(head);
            root.Children.Add(buttons);
            root.Children.Add(_status);
            root.Children.Add(new ScrollViewer { Content = rows, VerticalScrollBarVisibility = ScrollBarVisibility.Auto });
            Content = root;
        }

        private async Task SaveAsync()
        {
            // Every layer with a role is confirmed as the user's choice, so it isn't asked again.
            var roles = _choices
                .Where(kv => kv.Value.SelectedItem is string r && r != "—")
                .ToDictionary(kv => kv.Key, kv => (string)kv.Value.SelectedItem);
            _status.Text = "Saving…";
            IsEnabled = false;
            try
            {
                Result = await _api.SetLayerRolesAsync(_projectId, roles);
                DialogResult = true;
            }
            catch (Exception e)
            {
                _status.Text = "Couldn't save: " + e.Message;
                IsEnabled = true;
            }
        }
    }
}
