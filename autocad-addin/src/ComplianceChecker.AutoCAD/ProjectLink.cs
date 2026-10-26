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

        // ------------------------------------------------------------------ the saved site

        private const string SiteKey = "PERSPEC_COMPLIANCE_SITE";
        private const int Chunk = 240; // Xrecord strings stay short; the JSON is split across entries

        /// <summary>The site answers saved in the drawing (path → value, as JSON), or null.</summary>
        public static string? ReadSite(Document doc)
        {
            Database db = doc.Database;
            using Transaction tr = db.TransactionManager.StartOpenCloseTransaction();
            var nod = (DBDictionary)tr.GetObject(db.NamedObjectsDictionaryId, OpenMode.ForRead);
            if (!nod.Contains(SiteKey))
                return null;
            var rec = (Xrecord)tr.GetObject(nod.GetAt(SiteKey), OpenMode.ForRead);
            var sb = new System.Text.StringBuilder();
            foreach (TypedValue v in rec.Data?.AsArray() ?? [])
                if (v.TypeCode == (short)DxfCode.XTextString && v.Value is string part)
                    sb.Append(part);
            return sb.Length > 0 ? sb.ToString() : null;
        }

        /// <summary>
        /// Keep the site answers in the drawing, so the site travels with the DWG: a drawing opened on
        /// another computer, or checked against a server that no longer has its project, gets its site
        /// back without asking again. Like the project link, it never touches geometry.
        /// </summary>
        public static void WriteSite(Document doc, string json)
        {
            if (ReadSite(doc) == json)
                return; // unchanged: don't mark the drawing modified
            using DocumentLock _ = doc.LockDocument();
            Database db = doc.Database;
            using Transaction tr = db.TransactionManager.StartTransaction();
            var nod = (DBDictionary)tr.GetObject(db.NamedObjectsDictionaryId, OpenMode.ForWrite);
            Xrecord rec;
            if (nod.Contains(SiteKey))
            {
                rec = (Xrecord)tr.GetObject(nod.GetAt(SiteKey), OpenMode.ForWrite);
            }
            else
            {
                rec = new Xrecord();
                nod.SetAt(SiteKey, rec);
                tr.AddNewlyCreatedDBObject(rec, true);
            }
            var data = new ResultBuffer();
            for (int i = 0; i < json.Length; i += Chunk)
                data.Add(new TypedValue((int)DxfCode.XTextString, json.Substring(i, System.Math.Min(Chunk, json.Length - i))));
            rec.Data = data;
            tr.Commit();
        }
    }
}
