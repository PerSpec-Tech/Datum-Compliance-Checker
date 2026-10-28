using Autodesk.Revit.Attributes;
using Autodesk.Revit.DB;
using Autodesk.Revit.UI;
using ComplianceChecker.Storage;
using ComplianceChecker.UI;

namespace ComplianceChecker.Commands
{
    /// <summary>Pair this Revit with the web app. Touches no model data itself; Manual mode
    /// only so it can hand over to Site Setup, which saves the brief.</summary>
    [Transaction(TransactionMode.Manual)]
    public class PairCommand : IExternalCommand
    {
        public Result Execute(ExternalCommandData commandData, ref string message, ElementSet elements)
        {
            var settings = AddinSettings.Load();
            var window = new PairWindow(settings);
            new System.Windows.Interop.WindowInteropHelper(window).Owner = commandData.Application.MainWindowHandle;
            if (window.ShowDialog() != true)
                return Result.Cancelled;
            bool next = NextStep.Offer(
                "Revit is paired",
                $"Connected to {settings.ServerUrl}. You only do this once on this computer.",
                "Next: 2 Site Setup",
                "Tell the checker where the site is, which plot sides face a road and how wide they are.");
            if (next)
                return new SiteSetupCommand().Execute(commandData, ref message, elements);
            return Result.Succeeded;
        }
    }
}
