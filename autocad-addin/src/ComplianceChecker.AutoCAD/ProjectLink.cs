using Autodesk.AutoCAD.ApplicationServices;
using Autodesk.AutoCAD.DatabaseServices;

namespace ComplianceChecker.AutoCAD
{
    /// <summary>
    /// Which server project this drawing belongs to, kept in the drawing's named-object dictionary
    /// (an Xrecord). It is the plug-in's only write to the drawing: geometry is never changed.
    /// </summary>
    internal static class ProjectLink
    {
        private const string Key = "PERSPEC_COMPLIANCE";

        public static string? Read(Document doc)
        {
            Database db = doc.Database;
            using Transaction tr = db.TransactionManager.StartOpenCloseTransaction();
            var nod = (DBDictionary)tr.GetObject(db.NamedObjectsDictionaryId, OpenMode.ForRead);
            if (!nod.Contains(Key))
                return null;
            var rec = (Xrecord)tr.GetObject(nod.GetAt(Key), OpenMode.ForRead);
            foreach (TypedValue v in rec.Data?.AsArray() ?? [])
                if (v.TypeCode == (short)DxfCode.Text && v.Value is string id && id.Length > 0)
                    return id;
            return null;
        }

        public static void Write(Document doc, string projectId)
        {
            using DocumentLock _ = doc.LockDocument();
            Database db = doc.Database;
            using Transaction tr = db.TransactionManager.StartTransaction();
            var nod = (DBDictionary)tr.GetObject(db.NamedObjectsDictionaryId, OpenMode.ForWrite);
            Xrecord rec;
            if (nod.Contains(Key))
            {
                rec = (Xrecord)tr.GetObject(nod.GetAt(Key), OpenMode.ForWrite);
            }
            else
            {
                rec = new Xrecord();
                nod.SetAt(Key, rec);
                tr.AddNewlyCreatedDBObject(rec, true);
            }
            rec.Data = new ResultBuffer(new TypedValue((int)DxfCode.Text, projectId));
            tr.Commit();
        }
    }
}
