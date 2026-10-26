using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json;
using System.Threading.Tasks;
using Autodesk.AutoCAD.ApplicationServices;
using ComplianceChecker.Core.Api;

namespace ComplianceChecker.AutoCAD
{
    /// <summary>
    /// The project's site answers (location, plot, sides and roads, planning facts) kept in the
    /// drawing as well as on the server, so the site travels with the DWG. Saved from the site dialog,
    /// refreshed from the server after each check (a site set on the web comes into the drawing), and
    /// replayed when the drawing starts a new server project (another computer or server).
    /// </summary>
    internal static class SiteStore
    {
        public static Dictionary<string, JsonElement> Read(Document doc)
        {
            try
            {
                string? json = ProjectLink.ReadSite(doc);
                return json is null ? new() : JsonSerializer.Deserialize<Dictionary<string, JsonElement>>(json) ?? new();
            }
            catch (Exception e)
            {
                Log.Error("site in drawing unreadable", e);
                return new();
            }
        }

        /// <summary>Merge answers into the drawing's copy (newer values win).</summary>
        public static void Merge(Document doc, IReadOnlyDictionary<string, object?> answers)
        {
            if (answers.Count == 0)
                return;
            var all = Read(doc);
            foreach (var (path, value) in answers)
                all[path] = JsonSerializer.SerializeToElement(value);
            ProjectLink.WriteSite(doc, JsonSerializer.Serialize(all.OrderBy(kv => kv.Key, StringComparer.Ordinal).ToDictionary(kv => kv.Key, kv => kv.Value)));
        }

        /// <summary>A new server project for this drawing: send it the site the drawing remembers.</summary>
        public static async Task ReplayAsync(Document doc, ApiClient api, string projectId)
        {
            var saved = Read(doc);
            if (saved.Count == 0)
                return;
            await api.PatchBriefAsync(projectId, saved.ToDictionary(kv => kv.Key, kv => (object?)kv.Value));
            Log.Info($"site replayed from the drawing into {projectId}: {saved.Count} answers");
        }

        /// <summary>After a check: copy the project's saved answers (set here or on the web) into the drawing.</summary>
        public static async Task PullAsync(Document doc, ApiClient api, string projectId)
        {
            IReadOnlyDictionary<string, JsonElement> brief = await api.GetBriefAsync(projectId);
            if (brief.Count > 0)
                Merge(doc, brief.ToDictionary(kv => kv.Key, kv => (object?)kv.Value));
        }
    }
}
