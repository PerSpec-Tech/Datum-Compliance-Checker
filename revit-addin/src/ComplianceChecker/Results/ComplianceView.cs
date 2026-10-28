using System;
using System.Collections.Generic;
using System.Linq;
using Autodesk.Revit.DB;
using ComplianceChecker.Core.Results;
using ComplianceChecker.Generated;

namespace ComplianceChecker.Results
{
    /// <summary>
    /// The "Compliance Check" 3D view (P5.8): fail red, cannot-verify amber, pass green, everything else
    /// halftone. Only this view's graphic overrides change — never elements or other views (D11).
    /// Rooms aren't drawn in 3D; their results are reached through the results pane.
    /// </summary>
    public static class ComplianceView
    {
        public const string ViewName = "Datum Check";
        /// <summary>The view's name before Datum: an existing one is renamed, not duplicated.</summary>
        private const string OldViewName = "Compliance Check";

        private static readonly Color Fail = new(220, 38, 38);
        private static readonly Color Unverifiable = new(245, 158, 11);
        private static readonly Color Pass = new(22, 163, 74);

        public static View3D Apply(Document doc, ReportView report)
        {
            using var t = new Transaction(doc, "Datum: update Compliance Check view");
            t.Start();
            View3D view = GetOrCreate(doc);
            ElementId solid = SolidFill(doc);

            var status = new Dictionary<ElementId, Status>();
            foreach (var (uniqueId, s) in report.ElementStatus)
                if (doc.GetElement(uniqueId) is Element e)
                    status[e.Id] = s;

            foreach (Element e in new FilteredElementCollector(doc, view.Id).WhereElementIsNotElementType())
            {
                OverrideGraphicSettings ogs = status.TryGetValue(e.Id, out Status s) ? Coloured(Colour(s), solid) : new OverrideGraphicSettings().SetHalftone(true);
                try
                {
                    view.SetElementOverrides(e.Id, ogs);
                }
                catch (Exception)
                {
                    // some elements (e.g. view-specific ones) can't take overrides: skip them
                }
            }
            t.Commit();
            return view;
        }

        private static View3D GetOrCreate(Document doc)
        {
            View3D? existing = new FilteredElementCollector(doc).OfClass(typeof(View3D)).Cast<View3D>()
                .FirstOrDefault(v => !v.IsTemplate && (v.Name == ViewName || v.Name == OldViewName));
            if (existing is not null)
            {
                if (existing.Name != ViewName)
                    existing.Name = ViewName;
                return existing;
            }
            ViewFamilyType type = new FilteredElementCollector(doc).OfClass(typeof(ViewFamilyType)).Cast<ViewFamilyType>()
                .First(v => v.ViewFamily == ViewFamily.ThreeDimensional);
            View3D view = View3D.CreateIsometric(doc, type.Id);
            view.Name = ViewName;
            view.DisplayStyle = DisplayStyle.ShadingWithEdges;
            return view;
        }

        private static OverrideGraphicSettings Coloured(Color c, ElementId solid)
        {
            var ogs = new OverrideGraphicSettings()
                .SetProjectionLineColor(c)
                .SetCutLineColor(c)
                .SetSurfaceForegroundPatternColor(c)
                .SetCutForegroundPatternColor(c);
            if (solid != ElementId.InvalidElementId)
            {
                ogs.SetSurfaceForegroundPatternId(solid);
                ogs.SetCutForegroundPatternId(solid);
            }
            return ogs;
        }

        private static Color Colour(Status s) => s switch
        {
            Status.Fail => Fail,
            Status.Unverifiable => Unverifiable,
            _ => Pass,
        };

        private static ElementId SolidFill(Document doc) =>
            new FilteredElementCollector(doc).OfClass(typeof(FillPatternElement)).Cast<FillPatternElement>()
                .FirstOrDefault(f => f.GetFillPattern().IsSolidFill)?.Id ?? ElementId.InvalidElementId;
    }
}
