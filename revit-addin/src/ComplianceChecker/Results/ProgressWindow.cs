using System;
using System.Windows;
using System.Windows.Controls;

namespace ComplianceChecker.Results
{
    /// <summary>Modeless progress window: Revit stays usable while the check runs.</summary>
    internal sealed class ProgressWindow : Window
    {
        private readonly TextBlock _stage = new() { FontWeight = FontWeights.SemiBold, Margin = new Thickness(0, 0, 0, 4) };
        private readonly TextBlock _message = new() { TextWrapping = TextWrapping.Wrap, MinHeight = 36 };
        private readonly ProgressBar _bar = new() { Height = 14, Minimum = 0, Maximum = 100, Margin = new Thickness(0, 8, 0, 0) };

        public event Action? CancelRequested;

        public ProgressWindow()
        {
            Title = "Datum — checking";
            Width = 420;
            SizeToContent = SizeToContent.Height;
            ResizeMode = ResizeMode.NoResize;
            WindowStartupLocation = WindowStartupLocation.CenterScreen;
            ShowInTaskbar = false;
            var cancel = new Button { Content = "Cancel", Width = 90, HorizontalAlignment = HorizontalAlignment.Right, Margin = new Thickness(0, 10, 0, 0) };
            cancel.Click += (_, _) => CancelRequested?.Invoke();
            var panel = new StackPanel { Margin = new Thickness(16) };
            panel.Children.Add(_stage);
            panel.Children.Add(_message);
            panel.Children.Add(_bar);
            panel.Children.Add(cancel);
            Content = panel;
            Update("Starting", 0, "Exporting the model…");
        }

        /// <summary>Thread-safe: may be called from the background task.</summary>
        public void Update(string stage, double? pct, string? message) =>
            Dispatcher.BeginInvoke(() =>
            {
                _stage.Text = Pretty(stage);
                if (message is not null)
                    _message.Text = message;
                if (pct is double p)
                    _bar.Value = Math.Clamp(p, 0, 100);
                _bar.IsIndeterminate = pct is null;
            });

        public void CloseSafe() => Dispatcher.BeginInvoke(Close);

        private static string Pretty(string stage) => stage switch
        {
            "resolve_authority" => "Finding the planning authority",
            "overlays" => "Checking metro TOD zone",
            "classify_usage" => "Classifying rooms (Nemotron)",
            "derive" => "Measuring the model",
            "evaluate" => "Checking rules",
            "freshness" => "Checking for amendments (Tavily)",
            "plan_questions" => "Working out what's missing",
            "explain" => "Writing the summary (Nemotron)",
            "done" => "Done",
            _ => char.ToUpperInvariant(stage[0]) + stage[1..].Replace('_', ' '),
        };
    }
}
