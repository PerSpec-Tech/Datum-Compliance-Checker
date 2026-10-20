using Autodesk.Revit.Attributes;
using Autodesk.Revit.DB;
using Autodesk.Revit.UI;
using ComplianceChecker.Core.Model;
using ComplianceChecker.Export;
using ComplianceChecker.SiteSetup;
using ComplianceChecker.Storage;

namespace ComplianceChecker.Commands
{
    /// <summary>Site Setup (P5.4). Writes only the brief in Extensible Storage (D11).</summary>
    [Transaction(TransactionMode.Manual)]
    public class SiteSetupCommand : IExternalCommand
    {
        public Result Execute(ExternalCommandData commandData, ref string message, ElementSet elements)
        {
            UIApplication app = commandData.Application;
            Document doc = app.ActiveUIDocument.Document;
            Brief brief = BriefStore.Read(doc);
            RawModel site = RevitExporter.ReadSite(doc);

            var window = new SiteSetupWindow(brief, site);
            new System.Windows.Interop.WindowInteropHelper(window).Owner = app.MainWindowHandle;
            bool? ok = window.ShowDialog();

            if (window.DrawPropertyLinesRequested)
            {
                // Revit's own Property Line tool runs after this command returns.
                app.PostCommand(RevitCommandId.LookupPostableCommandId(PostableCommand.PropertyLine));
                return Result.Succeeded;
            }
            if (ok != true)
                return Result.Cancelled;
            BriefStore.Write(doc, window.Result);
            return Result.Succeeded;
        }
    }
}
