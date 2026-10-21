using System;
using Autodesk.AutoCAD.ApplicationServices;
using Autodesk.AutoCAD.Runtime;
using ComplianceChecker.Core.Api;
using ComplianceChecker.Storage;
using ComplianceChecker.UI;
using AcApp = Autodesk.AutoCAD.ApplicationServices.Application;

namespace ComplianceChecker.AutoCAD
{
    /// <summary>The plug-in's commands (also on the Compliance ribbon tab).</summary>
    public sealed class Commands
    {
        private static Document? Doc => AcApp.DocumentManager.MdiActiveDocument;

        /// <summary>Pair this computer with the web app (shared with the Revit add-in).</summary>
        [CommandMethod("CCPAIR")]
        public void Pair()
        {
            if (AcApp.ShowModalWindow(new PairWindow(AddinSettings.Load())) == true)
                Doc?.Editor.WriteMessage("\nCompliance: paired. Next: Compliance › 2 Layers, or 4 Run Check.");
        }

        /// <summary>Send the drawing and review what each layer is.</summary>
        [CommandMethod("CCLAYERS")]
        public async void Layers()
        {
            if (Doc is not { } doc || Checker.Api(doc.Editor) is not { } api)
                return;
            try
            {
                string pid = await Checker.SendAsync(doc, api);
                if (AcApp.ShowModalWindow(new LayersWindow(api, pid, Checker.Upload!)) == true)
                    doc.Editor.WriteMessage("\nCompliance: layers saved. Next: Compliance › 3 Site.");
            }
            catch (System.Exception e)
            {
                doc.Editor.WriteMessage("\nCompliance: " + e.Message);
            }
        }

        /// <summary>Send the drawing and open the site setup (map, plot, roads) in the browser.</summary>
        [CommandMethod("CCSITE")]
        public async void Site()
        {
            if (Doc is not { } doc || Checker.Api(doc.Editor) is not { } api)
                return;
            try
            {
                string pid = await Checker.SendAsync(doc, api);
                Checker.OpenInBrowser($"/w/{Uri.EscapeDataString(pid)}?site=1");
                doc.Editor.WriteMessage("\nCompliance: set the site in the browser (save & check), then come back and run 4 Run Check.");
            }
            catch (System.Exception e)
            {
                doc.Editor.WriteMessage("\nCompliance: " + e.Message);
            }
        }

        [CommandMethod("CCCHECK")]
        public async void Check()
        {
            if (Doc is { } doc)
                await Checker.CheckAsync(doc);
        }

        [CommandMethod("CCRESULTS")]
        public void Results() => ResultsPalette.Toggle();

        /// <summary>The full report (printable) in the browser.</summary>
        [CommandMethod("CCREPORT")]
        public void Report()
        {
            if (ResultsPalette.Report is { } r)
                Checker.OpenInBrowser($"/reports/{Uri.EscapeDataString(r.Id)}");
            else if (Doc is { } doc && ProjectLink.Read(doc) is { } pid)
                Checker.OpenInBrowser($"/w/{Uri.EscapeDataString(pid)}");
            else
                Doc?.Editor.WriteMessage("\nCompliance: run a check first (Compliance › 4 Run Check).");
        }

        [CommandMethod("CCCLEAR")]
        public void Clear() => Highlighter.Clear();
    }
}
