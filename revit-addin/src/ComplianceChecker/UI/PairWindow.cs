using System;
using System.Text.RegularExpressions;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Controls;
using ComplianceChecker.Core.Api;
using ComplianceChecker.Storage;

namespace ComplianceChecker.UI
{
    /// <summary>Asks for the server URL and the 6-digit code shown in the web app, then stores the token.</summary>
    internal sealed class PairWindow : Window
    {
        private readonly TextBox _url = new() { Margin = new Thickness(0, 4, 0, 10) };
        private readonly TextBox _code = new() { Margin = new Thickness(0, 4, 0, 10), MaxLength = 6, FontSize = 18 };
        private readonly TextBlock _status = new() { TextWrapping = TextWrapping.Wrap, Margin = new Thickness(0, 6, 0, 0) };
        private readonly Button _pair = new() { Content = "Pair", Width = 90, IsDefault = true };

        public PairWindow(AddinSettings settings)
        {
            Title = "Compliance Checker — Pair with the web app";
            Width = 420;
            SizeToContent = SizeToContent.Height;
            ResizeMode = ResizeMode.NoResize;
            WindowStartupLocation = WindowStartupLocation.CenterScreen;
            _url.Text = settings.ServerUrl;

            var cancel = new Button { Content = "Cancel", Width = 90, IsCancel = true, Margin = new Thickness(8, 0, 0, 0) };
            var buttons = new StackPanel { Orientation = Orientation.Horizontal, HorizontalAlignment = HorizontalAlignment.Right, Margin = new Thickness(0, 10, 0, 0) };
            buttons.Children.Add(_pair);
            buttons.Children.Add(cancel);

            var panel = new StackPanel { Margin = new Thickness(16) };
            panel.Children.Add(new TextBlock { Text = "Open the compliance web app, choose “Pair Revit · AutoCAD”, and type the 6-digit code it shows. One pairing covers Revit and AutoCAD.", TextWrapping = TextWrapping.Wrap, Margin = new Thickness(0, 0, 0, 12) });
            panel.Children.Add(new TextBlock { Text = "Server URL" });
            panel.Children.Add(_url);
            panel.Children.Add(new TextBlock { Text = "Pairing code" });
            panel.Children.Add(_code);
            panel.Children.Add(_status);
            panel.Children.Add(buttons);
            Content = panel;

            _pair.Click += async (_, _) => await PairAsync(settings);
            Loaded += (_, _) => _code.Focus();
        }

        private async Task PairAsync(AddinSettings settings)
        {
            string url = _url.Text.Trim(), code = _code.Text.Trim();
            if (!Uri.TryCreate(url, UriKind.Absolute, out _))
            {
                _status.Text = "Enter a valid server URL, e.g. https://compliance.example.com";
                return;
            }
            if (!Regex.IsMatch(code, "^[0-9]{6}$"))
            {
                _status.Text = "The pairing code is 6 digits.";
                return;
            }
            _pair.IsEnabled = false;
            _status.Text = "Pairing…";
            try
            {
                string token = await new ApiClient(url, null).CompletePairingAsync(code, Environment.MachineName);
                AddinSettings.SaveToken(token);
                settings.ServerUrl = url;
                settings.Save();
                DialogResult = true;
            }
            catch (Exception e)
            {
                _status.Text = "Pairing failed: " + e.Message;
                _pair.IsEnabled = true;
            }
        }
    }
}
