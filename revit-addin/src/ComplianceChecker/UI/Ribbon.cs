using System.Reflection;
using System.Windows.Media;
using Autodesk.Revit.UI;
using ComplianceChecker.Commands;

namespace ComplianceChecker.UI
{
    internal static class Ribbon
    {
        public const string TabName = "Compliance";

        public static void Build(UIControlledApplication app)
        {
            app.CreateRibbonTab(TabName);
            RibbonPanel panel = app.CreateRibbonPanel(TabName, "Bylaw check");
            string assembly = Assembly.GetExecutingAssembly().Location;

            Add(panel, assembly, "cc_pair", "Pair", typeof(PairCommand),
                "Connect this Revit to the compliance web app using the 6-digit code it shows.", "P", Colors.SlateGray);
            Add(panel, assembly, "cc_site", "Site\nSetup", typeof(SiteSetupCommand),
                "Tag plot edges (road / neighbour), road widths and other declared site facts.", "S", Colors.SeaGreen);
            Add(panel, assembly, "cc_check", "Run\nCheck", typeof(CheckCommand),
                "Export the model, check it against UDCPR / NBC rules and show the results.", "✓", Colors.RoyalBlue);
            Add(panel, assembly, "cc_results", "Results", typeof(ResultsCommand),
                "Show the compliance results panel.", "R", Colors.DarkOrange);
            panel.AddSeparator();
            Add(panel, assembly, "cc_export", "Export\nJSON", typeof(ExportJsonCommand),
                "Save the exported building model as JSON (for checking the export; changes nothing).", "{}", Colors.DimGray);
        }

        private static void Add(RibbonPanel panel, string assembly, string name, string text,
            System.Type command, string tooltip, string glyph, Color color)
        {
            var data = new PushButtonData(name, text, assembly, command.FullName)
            {
                ToolTip = tooltip,
                LargeImage = Icons.Create(glyph, color, 32),
                Image = Icons.Create(glyph, color, 16),
            };
            panel.AddItem(data);
        }
    }
}
