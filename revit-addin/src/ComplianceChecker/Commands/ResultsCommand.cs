using Autodesk.Revit.Attributes;
using Autodesk.Revit.DB;
using Autodesk.Revit.UI;

namespace ComplianceChecker.Commands
{
    /// <summary>Show the results pane (P5.7).</summary>
    [Transaction(TransactionMode.ReadOnly)]
    public class ResultsCommand : IExternalCommand
    {
        public Result Execute(ExternalCommandData commandData, ref string message, ElementSet elements)
        {
            commandData.Application.GetDockablePane(App.ResultsPaneId).Show();
            return Result.Succeeded;
        }
    }
}
