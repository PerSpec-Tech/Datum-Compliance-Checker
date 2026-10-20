using Autodesk.Revit.Attributes;
using Autodesk.Revit.DB;
using Autodesk.Revit.UI;
using ComplianceChecker.Storage;
using ComplianceChecker.UI;

namespace ComplianceChecker.Commands
{
    /// <summary>Pair this Revit with the web app (P5.5). Touches no model data.</summary>
    [Transaction(TransactionMode.ReadOnly)]
    public class PairCommand : IExternalCommand
    {
        public Result Execute(ExternalCommandData commandData, ref string message, ElementSet elements)
        {
            var settings = AddinSettings.Load();
            var window = new PairWindow(settings);
            new System.Windows.Interop.WindowInteropHelper(window).Owner = commandData.Application.MainWindowHandle;
            if (window.ShowDialog() != true)
                return Result.Cancelled;
            TaskDialog.Show("Compliance Checker", $"Paired with {settings.ServerUrl}. You can now run checks.");
            return Result.Succeeded;
        }
    }
}
