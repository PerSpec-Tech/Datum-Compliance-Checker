using Autodesk.Revit.Attributes;
using Autodesk.Revit.DB;
using Autodesk.Revit.UI;
using ComplianceChecker.UI;

namespace ComplianceChecker.Commands
{
    /// <summary>
    /// Compliance lens on/off (P9.3): the buildable line and setback issues drawn over the current
    /// view. Transient graphics only; changes nothing in the model. Assign it a key (Revit
    /// Keyboard Shortcuts, e.g. Shift+L) to toggle it while modelling.
    /// </summary>
    [Transaction(TransactionMode.Manual)] // may hand over to Run Check; writes nothing itself
    public class LensCommand : IExternalCommand
    {
        public Result Execute(ExternalCommandData commandData, ref string message, ElementSet elements)
        {
            if (App.Current is null)
                return Result.Failed;
            Document doc = commandData.Application.ActiveUIDocument.Document;
            if (!App.Current.Live.HasPack(doc))
            {
                var r = NextStep.Missing(
                    "Run a check first",
                    "The lens draws the setbacks from this project's latest check, and there isn't one yet in this session.",
                    "3 Run Check now", "Then the lens and the live strip follow your edits.",
                    "Cancel", "");
                return r == TaskDialogResult.CommandLink1
                    ? new CheckCommand().Execute(commandData, ref message, elements)
                    : Result.Cancelled;
            }
            App.Current.Live.LensOn = !App.Current.Live.LensOn;
            return Result.Succeeded;
        }
    }
}
