using Autodesk.Revit.DB;

namespace ComplianceChecker.Export
{
    /// <summary>Revit internal units (feet) → SI.</summary>
    internal static class Units
    {
        public static double M(double feet) => UnitUtils.ConvertFromInternalUnits(feet, UnitTypeId.Meters);

        public static double M2(double squareFeet) => UnitUtils.ConvertFromInternalUnits(squareFeet, UnitTypeId.SquareMeters);
    }
}
