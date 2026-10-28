using System;
using System.IO;
using Autodesk.Revit.Attributes;
using Autodesk.Revit.DB;
using Autodesk.Revit.UI;
using ComplianceChecker.Core.Model;
using ComplianceChecker.Export;
using ComplianceChecker.Generated;
using ComplianceChecker.Storage;
using Microsoft.Win32;
using Result = Autodesk.Revit.UI.Result;

namespace ComplianceChecker.Commands
{
    /// <summary>
    /// Saves the exported BuildingModel as JSON (P5.2 manual check: `just validate &lt;file&gt;`).
    /// Read-only: nothing in the model changes.
    /// </summary>
    [Transaction(TransactionMode.Manual)]
    public class ExportJsonCommand : IExternalCommand
    {
        public Result Execute(ExternalCommandData commandData, ref string message, ElementSet elements)
        {
            Document doc = commandData.Application.ActiveUIDocument.Document;
            RawModel raw = RevitExporter.Read(doc, AddinInfo.Version);
            string json = ModelBuilder.Build(raw, BriefStore.Read(doc), DateTimeOffset.Now).ToJson();

            var dialog = new SaveFileDialog
            {
                Title = "Save exported building model",
                Filter = "JSON (*.json)|*.json",
                FileName = Path.GetFileNameWithoutExtension(raw.SourceFile ?? "model") + ".building-model.json",
            };
            if (dialog.ShowDialog() != true)
                return Result.Cancelled;
            File.WriteAllText(dialog.FileName, json);

            string summary =
                $"Levels {raw.Levels.Count} · rooms {raw.Rooms.Count} · areas {raw.Areas.Count} · stairs {raw.Stairs.Count} · " +
                $"doors {raw.Doors.Count} · property-line segments {raw.PropertyLineSegments.Count}";
            var td = new TaskDialog("Datum")
            {
                MainInstruction = "Model exported",
                MainContent = summary + (raw.Warnings.Count > 0 ? "\n\nWarnings:\n• " + string.Join("\n• ", raw.Warnings) : ""),
            };
            td.Show();
            return Result.Succeeded;
        }
    }
}
