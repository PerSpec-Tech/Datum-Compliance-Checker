using Autodesk.Revit.Attributes;
using Autodesk.Revit.DB;
using Autodesk.Revit.UI;
using ComplianceChecker.Core.Model;
using ComplianceChecker.Storage;
using ComplianceChecker.UI;

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
            Document doc = app.ActiveUIDocument.Document;

            if (string.IsNullOrEmpty(AddinSettings.LoadToken()))
            {
                var r = NextStep.Missing(
                    "Pair Revit first",
                    "This computer isn't connected to the compliance web app yet.",
                    "1 Pair now", "Get a 6-digit code from the web app's 'Pair Revit' page.",
                    "Cancel", "");
                return r == TaskDialogResult.CommandLink1
                    ? new PairCommand().Execute(commandData, ref message, elements)
                    : Result.Cancelled;
            }

            Brief brief = BriefStore.Read(doc);
            if (brief.Latitude is null && brief.Edges.Count == 0)
            {
                var r = NextStep.Missing(
                    "Site Setup hasn't been done for this project",
                    "Without the location and road widths, margins, FSI and TOD rules can't be checked; they will show as 'can't verify'.",
                    "2 Site Setup first", "Recommended: takes about a minute.",
                    "Run the check anyway", "You can answer the missing facts later.");
                if (r == TaskDialogResult.CommandLink1)
                    return new SiteSetupCommand().Execute(commandData, ref message, elements);
                if (r != TaskDialogResult.CommandLink2)
                    return Result.Cancelled;
            }

            App.Current.CheckRunner.Start(app, doc);
            return Result.Succeeded;
        }
    }
}
