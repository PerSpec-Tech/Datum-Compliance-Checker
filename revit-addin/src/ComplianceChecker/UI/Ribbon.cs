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

            // Numbered so the order is obvious: 1 Pair → 2 Site Setup → 3 Run Check.
            Add(panel, assembly, "cc_pair", "1 Pair", typeof(PairCommand),
                "Step 1, once per computer: connect this Revit to the compliance web app with the 6-digit code from its 'Pair Revit' page.", "1", Colors.SlateGray);
            Add(panel, assembly, "cc_site", "2 Site\nSetup", typeof(SiteSetupCommand),
                "Step 2, once per project: site location, which plot sides face a road and how wide each road is, occupancy and building type.", "2", Colors.SeaGreen);
            Add(panel, assembly, "cc_check", "3 Run\nCheck", typeof(CheckCommand),
                "Step 3, any time: send the model, check it against UDCPR / NBC and show the results. Run again after changes to see what was fixed.", "3", Colors.RoyalBlue);
            Add(panel, assembly, "cc_lens", "Lens", typeof(LensCommand),
                "Show or hide the buildable line and setback issues over the current view while you model. Changes nothing in the model. Tip: give it a shortcut (e.g. Shift+L) in Keyboard Shortcuts.", "◎", Colors.DimGray);
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
