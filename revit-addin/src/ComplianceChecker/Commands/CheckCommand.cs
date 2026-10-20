using Autodesk.Revit.Attributes;
using Autodesk.Revit.DB;
using Autodesk.Revit.UI;

namespace ComplianceChecker.Commands
{
    /// <summary>Run Check (P5.6): export → upload → check → results, without blocking Revit.</summary>
    [Transaction(TransactionMode.Manual)]
    public class CheckCommand : IExternalCommand
    {
        public Result Execute(ExternalCommandData commandData, ref string message, ElementSet elements)
        {
            if (App.Current is null)
            {
                message = "The Compliance Checker add-in didn't start correctly.";
                return Result.Failed;
            }
            UIApplication app = commandData.Application;
            App.Current.CheckRunner.Start(app, app.ActiveUIDocument.Document);
            return Result.Succeeded;
        }
    }
}
