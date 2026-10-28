using System;
using Autodesk.Revit.DB;
using Autodesk.Revit.DB.ExtensibleStorage;
using ComplianceChecker.Core.Model;

namespace ComplianceChecker.Storage
{
    /// <summary>
    /// Saves the declared site facts (<see cref="Brief"/>) as one JSON string in Extensible Storage on
    /// ProjectInformation, so they travel with the .rvt. This is the ONLY model write the add-in makes
    /// apart from the "Compliance Check" view (D11).
    /// </summary>
    public static class BriefStore
    {
        private const string Field = "BriefJson";

        public static Brief Read(Document doc)
        {
            Schema? schema = Schema.Lookup(Ids.BriefSchema);
            if (schema is null)
                return new Brief();
            Entity entity = doc.ProjectInformation.GetEntity(schema);
            return entity.IsValid() ? Brief.FromJson(entity.Get<string>(Field)) : new Brief();
        }

        public static void Write(Document doc, Brief brief)
        {
            using var t = new Transaction(doc, "Datum: save site setup");
            t.Start();
            var entity = new Entity(GetOrCreateSchema());
            entity.Set(Field, brief.ToJson());
            doc.ProjectInformation.SetEntity(entity);
            t.Commit();
        }

        private static Schema GetOrCreateSchema()
        {
            Schema? existing = Schema.Lookup(Ids.BriefSchema);
            if (existing is not null)
                return existing;
            var b = new SchemaBuilder(Ids.BriefSchema);
            b.SetSchemaName("ComplianceCheckerBrief");
            b.SetDocumentation("Declared site facts for the Compliance Checker add-in (JSON).");
            b.SetReadAccessLevel(AccessLevel.Public);
            b.SetWriteAccessLevel(AccessLevel.Vendor);
            b.SetVendorId(Ids.VendorId); // must match <VendorId> in ComplianceChecker.addin
            b.AddSimpleField(Field, typeof(string));
            return b.Finish();
        }
    }

    public static class Ids
    {
        /// <summary>Fixed forever: changing it would orphan briefs already saved in models.</summary>
        public static readonly Guid BriefSchema = new("b7d6a3e2-4c1f-4e8a-9d2b-6f0a1c3e5b79");

        public const string VendorId = "PERSPEC";
    }
}
