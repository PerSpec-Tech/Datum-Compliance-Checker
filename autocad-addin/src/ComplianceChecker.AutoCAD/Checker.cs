using System;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Threading.Tasks;
using Autodesk.AutoCAD.ApplicationServices;
using Autodesk.AutoCAD.DatabaseServices;
using Autodesk.AutoCAD.EditorInput;
using ComplianceChecker.Core.Api;
using ComplianceChecker.Generated;
using ComplianceChecker.Storage;

namespace ComplianceChecker.AutoCAD
{
    /// <summary>
    /// Sends the open drawing to the server and runs the check (P11.3). The drawing goes as DXF and
    /// is read by the server's DXF reader, the same one the web app uses, so the two always agree;
    /// entity handles survive the export, so results point back at the drawing's own entities.
    /// </summary>
    internal static class Checker
    {
        public static CheckReport? Report { get; private set; }
        public static DrawingUpload? Upload { get; private set; }
        private static bool _busy;

        public static string ServerUrl => AddinSettings.Load().ServerUrl.TrimEnd('/');

        /// <summary>The API client, or null (with a message) if this computer isn't paired yet.</summary>
        public static ApiClient? Api(Editor ed)
        {
            string? token = AddinSettings.LoadToken();
            if (token is null)
            {
                ed.WriteMessage("\nDatum: pair with the web app first (Datum › 1 Pair, or CCPAIR).");
                return null;
            }
            return new ApiClient(ServerUrl, token);
        }

        /// <summary>Export the drawing and upload it; returns the server project id.</summary>
        public static async Task<string> SendAsync(Document doc, ApiClient api)
        {
            byte[] dxf = ExportDxf(doc);
            string name = Path.GetFileNameWithoutExtension(doc.Name);
            string? pid = ProjectLink.Read(doc);
            if (pid is not null)
            {
                try
                {
                    Upload = await api.UploadDxfAsync(pid, dxf);
                    return pid;
                }
                catch (ApiException e) when (e.Status == 404)
                {
                    // the project is gone from the server (e.g. a fresh install): start a new one
                }
            }
            pid = await api.CreateProjectAsync(name);
            ProjectLink.Write(doc, pid);
            Upload = await api.UploadDxfAsync(pid, dxf);
            // A new project for a drawing that already has a site (another computer or server): bring it along.
            try
            {
                await SiteStore.ReplayAsync(doc, api, pid);
            }
            catch (Exception e)
            {
                Log.Error("site replay", e);
            }
            return pid;
        }

        /// <summary>The drawing as DXF bytes. DxfOut writes a file; the document itself is untouched.</summary>
        private static byte[] ExportDxf(Document doc)
        {
            Log.Info("exporting DXF");
            string tmp = Path.Combine(Path.GetTempPath(), $"compliance-{Guid.NewGuid():N}.dxf");
            try
            {
                using (doc.LockDocument())
                    doc.Database.DxfOut(tmp, 16, DwgVersion.Current);
                return File.ReadAllBytes(tmp);
            }
            finally
            {
                if (File.Exists(tmp))
                    File.Delete(tmp);
            }
        }

        /// <summary>Layers the reader doesn't know yet, or only guessed: ask before checking.</summary>
        public static bool NeedsLayerCheck(DrawingUpload? up) =>
            up is not null && (up.Unmapped > 0 || (up.Layers ?? []).Any(l => l.Source == "suggested"));

        public static async Task CheckAsync(Document doc)
        {
            Editor ed = doc.Editor;
            if (_busy)
            {
                ed.WriteMessage("\nDatum: a check is already running.");
                return;
            }
            ApiClient? api = Api(ed);
            if (api is null)
                return;
            _busy = true;
            try
            {
                Log.Info($"CCCHECK {doc.Name}");
                ed.WriteMessage("\nDatum: sending the drawing…");
                ResultsPalette.SetStatus("Sending the drawing…");
                string pid = await SendAsync(doc, api);
                Log.Info($"sent: project {pid}, {(Upload?.Counts is { } c && c.TryGetValue("spaces", out int n) ? n : 0)} rooms, {Upload?.Unmapped} unknown layers");
                if (NeedsLayerCheck(Upload))
                {
                    var window = new LayersWindow(api, pid, Upload!);
                    if (Application.ShowModalWindow(window) != true)
                    {
                        ResultsPalette.SetStatus("Check cancelled: confirm the layers first.");
                        return;
                    }
                    Upload = window.Result ?? Upload;
                }
                // A drawing that doesn't know where it is goes to the site setup first (which checks after).
                if (!HasLocation(await api.GetModelJsonAsync(pid)))
                {
                    ed.WriteMessage("\nDatum: this drawing has no location yet. Opening the site setup…");
                    ResultsPalette.SetStatus("Set the site first: where it is, the plot and the road.");
                    _busy = false;
                    await SiteSetup.RunAsync(doc, api);
                    return;
                }
                ResultsPalette.SetStatus("Checking…");
                ed.WriteMessage("\nDatum: checking…");
                string job = await api.StartCheckAsync(pid);
                string? reportId = null;
                await foreach (JobEvent e in api.StreamJobAsync(job))
                {
                    if (e.Stage == "error")
                        throw new InvalidOperationException(e.Error ?? e.Msg ?? "the check failed");
                    if (e.Stage == "done")
                        reportId = e.ReportId;
                    else
                        ResultsPalette.SetStatus($"Checking… {e.Pct ?? 0:0}%  {e.Msg}");
                }
                if (reportId is null)
                    throw new InvalidOperationException("the check ended without a report");
                Report = await api.GetReportAsync(reportId);
                try
                {
                    Markup.Current = Markup.FromModelJson(await api.GetModelJsonAsync(pid), doc.Database);
                }
                catch (Exception e)
                {
                    Log.Error("model for markup", e); // plot sides and whole-building results won't be clouded
                }
                ResultsPalette.ShowReport(doc, Report, pid);
                int clouds = 0;
                try
                {
                    clouds = Highlighter.Show(doc, Report);
                }
                catch (Exception e)
                {
                    Log.Error("clouds", e);
                    ed.WriteMessage($"\nDatum: couldn't draw the issue clouds ({e.Message}).");
                }
                try
                {
                    await LiveMode.StartAsync(doc, api, pid);
                }
                catch (Exception e)
                {
                    Log.Error("live start", e); // the check's results stand without the preview
                }
                try
                {
                    await SiteStore.PullAsync(doc, api, pid); // a site set on the web comes into the drawing
                }
                catch (Exception e)
                {
                    Log.Error("site pull", e);
                }
                var s = Report.Summary;
                Log.Info($"report {reportId}: {s.Fail} fail, {s.Unverifiable} unverifiable, {clouds} clouds");
                ed.WriteMessage($"\nDatum: {s.Fail} fail · {s.Unverifiable} can't verify · {s.Pass} pass. "
                                + $"Issues are clouded on layer {Highlighter.LayerName}; see the Compliance palette.");
            }
            catch (Exception e)
            {
                Log.Error("CCCHECK", e);
                ed.WriteMessage("\nDatum: the check stopped: " + e.Message + $"\n  (details in {Log.FilePath})");
                ResultsPalette.SetStatus("The check stopped: " + e.Message);
            }
            finally
            {
                _busy = false;
            }
        }

        private static bool HasLocation(string modelJson)
        {
            try
            {
                using var json = System.Text.Json.JsonDocument.Parse(modelJson);
                return json.RootElement.GetProperty("model").GetProperty("project").GetProperty("location")
                    .GetProperty("value").ValueKind == System.Text.Json.JsonValueKind.Object;
            }
            catch (Exception)
            {
                return true; // unreadable: let the server say what's missing
            }
        }

        public static void OpenInBrowser(string path)
        {
            try
            {
                Process.Start(new ProcessStartInfo(ServerUrl + path) { UseShellExecute = true });
            }
            catch (Exception)
            {
                // no default browser: nothing more we can do
            }
        }
    }
}
