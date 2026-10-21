using System;
using System.Windows.Input;
using Autodesk.Windows;
using AcApp = Autodesk.AutoCAD.ApplicationServices.Application;

namespace ComplianceChecker.AutoCAD
{
    /// <summary>
    /// The Compliance ribbon tab: numbered steps (as in Revit) and the results. Each button runs its
    /// command through the command line, so it is undoable, repeatable and scriptable.
    /// </summary>
    internal static class Ribbon
    {
        private const string TabId = "PERSPEC_COMPLIANCE_TAB";

        /// <summary>Adds the tab (once; safe to call again). Returns false if there is no ribbon.</summary>
        public static bool Build()
        {
            try
            {
                RibbonControl ribbon = ComponentManager.Ribbon;
                if (ribbon is null)
                {
                    Log.Info("ribbon: not available yet");
                    return false;
                }
                if (ribbon.FindTab(TabId) is { } existing)
                {
                    existing.IsVisible = true;
                    return true;
                }
                AddTab(ribbon);
                Log.Info("ribbon: Compliance tab added");
                return true;
            }
            catch (System.Exception e)
            {
                Log.Error("ribbon", e);
                return false;
            }
        }

        private static void AddTab(RibbonControl ribbon)
        {
            var tab = new RibbonTab { Title = "Compliance", Id = TabId };

            tab.Panels.Add(Panel("Set up",
                Button("1 Pair", "CCPAIR", Icons.Plug, "Pair with the compliance web app (once per computer)."),
                Button("2 Layers", "CCLAYERS", Icons.Layers, "Say what each layer is: plot, floors, rooms… PreDCR layers are known already."),
                Button("3 Site", "CCSITE", Icons.Pin, "Place the drawing on the map, draw or confirm the plot, tag the roads.")));
            tab.Panels.Add(Panel("Check",
                Button("4 Run Check", "CCCHECK", Icons.Check, "Send the drawing and check it against UDCPR 2020 / NBC 2016.", large: true)));
            tab.Panels.Add(Panel("Results",
                Button("Results", "CCRESULTS", Icons.List, "Show the results palette."),
                Button("Report", "CCREPORT", Icons.Book, "Open the full report (printable) in the browser."),
                Button("Clear", "CCCLEAR", Icons.Cross, "Remove the red highlights from the drawing.")));
            ribbon.Tabs.Add(tab);
        }

        private static RibbonPanel Panel(string title, params RibbonItem[] items)
        {
            var source = new RibbonPanelSource { Title = title };
            foreach (RibbonItem item in items)
                source.Items.Add(item);
            return new RibbonPanel { Source = source };
        }

        private static RibbonButton Button(string text, string command, string icon, string tip, bool large = false) =>
            new()
            {
                Text = text,
                ShowText = true,
                ShowImage = true,
                Size = large ? RibbonItemSize.Large : RibbonItemSize.Standard,
                Orientation = large ? System.Windows.Controls.Orientation.Vertical : System.Windows.Controls.Orientation.Horizontal,
                Image = Icons.Image(icon, 16),
                LargeImage = Icons.Image(icon, 32),
                ToolTip = tip,
                CommandParameter = command,
                CommandHandler = Runner.Instance,
            };

        /// <summary>Runs a button's command on the active drawing.</summary>
        private sealed class Runner : ICommand
        {
            public static readonly Runner Instance = new();

            public event EventHandler? CanExecuteChanged { add { } remove { } }

            public bool CanExecute(object? parameter) => true;

            public void Execute(object? parameter)
            {
                if (parameter is RibbonButton { CommandParameter: string cmd })
                    AcApp.DocumentManager.MdiActiveDocument?.SendStringToExecute("_" + cmd + " ", true, false, true);
            }
        }
    }
}
