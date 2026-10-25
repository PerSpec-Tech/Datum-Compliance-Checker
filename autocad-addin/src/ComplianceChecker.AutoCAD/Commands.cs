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
                Log.Error("CCLAYERS", e);
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
                await SiteSetup.RunAsync(doc, api);
            }
            catch (System.Exception e)
            {
                Log.Error("CCSITE", e);
                doc.Editor.WriteMessage("\nCompliance: " + e.Message);
            }
        }

        [CommandMethod("CCCHECK")]
        public async void Check()
        {
            try
            {
                if (Doc is { } doc)
                    await Checker.CheckAsync(doc);
            }
            catch (System.Exception e)
            {
                Log.Error("CCCHECK (outer)", e);
                Doc?.Editor.WriteMessage($"\nCompliance: {e.Message} (details in {Log.FilePath})");
            }
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

        /// <summary>Put the Compliance tab back on the ribbon (e.g. after changing workspace).</summary>
        [CommandMethod("CCRIBBON")]
        public void ShowRibbon()
        {
            bool ok = Ribbon.Build();
            Doc?.Editor.WriteMessage(ok
                ? "\nCompliance: the Compliance tab is on the ribbon."
                : $"\nCompliance: no ribbon to add the tab to (type RIBBON to show it, then CCRIBBON). Details in {Log.FilePath}");
        }

        /// <summary>Pause or resume the live preview of margins and FSI while drawing.</summary>
        [CommandMethod("CCLIVE")]
        public void Live() => Doc?.Editor.WriteMessage("\nCompliance: " + LiveMode.Toggle());

        /// <summary>Show or hide the lens: the buildable line, and outlines that cross it in red.</summary>
        [CommandMethod("CCLENS")]
        public void Lens() => Doc?.Editor.WriteMessage("\nCompliance: " + LiveMode.ToggleLens());

        [CommandMethod("CCCLEAR")]
        public void Clear()
        {
            Highlighter.Clear(Doc);
            Doc?.Editor.WriteMessage($"\nCompliance: issue clouds removed (layer {Highlighter.LayerName} kept, now empty).");
        }
    }
}
