using System;
using System.Collections.Generic;
using System.Threading;
using System.Threading.Tasks;
using Autodesk.Revit.DB;
using Autodesk.Revit.UI;
using ComplianceChecker.Core.Api;
using ComplianceChecker.Core.Model;
using ComplianceChecker.Core.Results;
using ComplianceChecker.Export;
using ComplianceChecker.Generated;
using ComplianceChecker.Storage;

namespace ComplianceChecker.Results
{
    /// <summary>
    /// Runs one check (P5.6): export on Revit's main thread → upload, run and stream on a background
    /// task → apply the report back on the main thread through <see cref="UiActionQueue"/>.
    /// Never blocks the Revit UI.
    /// </summary>
    public sealed class CheckRunner : IDisposable
    {
        private readonly ResultsPane _pane;
        private readonly UiActionQueue _ui;
        private readonly Dictionary<string, CheckReport> _lastReport = new(); // per document, this session
        private CancellationTokenSource? _running;

        public CheckRunner(ResultsPane pane, UiActionQueue ui)
        {
            _pane = pane;
            _ui = ui;
        }

        public bool IsRunning => _running is not null;

        /// <summary>Call from an external command (main thread).</summary>
        public void Start(UIApplication app, Document doc)
        {
            if (IsRunning)
            {
                TaskDialog.Show("Datum", "A check is already running.");
                return;
            }
            AddinSettings settings = AddinSettings.Load();
            string? token = AddinSettings.LoadToken();
            if (token is null)
            {
                TaskDialog.Show("Datum", "Pair with the web app first (Datum › Pair).");
                return;
            }

            // Main thread: read the model (read-only) and the declared brief.
            Brief brief = BriefStore.Read(doc);
            RawModel raw = RevitExporter.Read(doc, AddinInfo.Version);
            BuildingModel model = ModelBuilder.Build(raw, brief, DateTimeOffset.Now);
            string docKey = string.IsNullOrEmpty(doc.PathName) ? doc.Title : doc.PathName;

            var progress = new ProgressWindow();
            new System.Windows.Interop.WindowInteropHelper(progress).Owner = app.MainWindowHandle;
            var cts = new CancellationTokenSource();
            progress.CancelRequested += cts.Cancel;
            progress.Show();
            _running = cts;

            Task.Run(async () =>
            {
                try
                {
                    var api = new ApiClient(settings.ServerUrl, token);
                    string projectId = brief.ProjectId ?? await NewProject(api, model, doc, brief, cts.Token);
                    progress.Update("upload", 5, "Uploading the model…");
                    try
                    {
                        await api.PutModelAsync(projectId, model, cts.Token);
                    }
                    catch (ApiException e) when (e.Status == 404)
                    {
                        // The server no longer knows this project (e.g. it was reset): start a new one.
                        projectId = await NewProject(api, model, doc, brief, cts.Token);
                        await api.PutModelAsync(projectId, model, cts.Token);
                    }

                    string jobId = await api.StartCheckAsync(projectId, cts.Token);
                    string? reportId = null;
                    await foreach (JobEvent e in api.StreamJobAsync(jobId, cts.Token))
                    {
                        if (e.Stage == "error")
                            throw new InvalidOperationException(e.Error ?? e.Msg ?? "the check failed on the server");
                        progress.Update(e.Stage, e.Pct, e.Msg);
                        reportId = e.ReportId ?? reportId;
                    }
                    if (reportId is null)
                        throw new InvalidOperationException("the server finished without a report");

                    CheckReport report = await api.GetReportAsync(reportId, cts.Token);
                    Core.Live.LivePack? pack = null;
                    try
                    {
                        pack = await api.GetLivePackAsync(projectId, cts.Token);
                    }
                    catch (Exception)
                    {
                        // live mode is optional; the report still applies
                    }
                    _ui.Post(uiapp =>
                    {
                        Apply(uiapp, docKey, report, raw.Warnings);
                        App.Current?.Live.SetPack(uiapp, docKey, pack);
                    });
                }
                catch (OperationCanceledException)
                {
                    // user cancelled: nothing to apply
                }
                catch (Exception e)
                {
                    _ui.Post(_ => TaskDialog.Show("Datum", "The check didn't complete:\n" + e.Message));
                }
                finally
                {
                    progress.CloseSafe();
                    _running = null;
                    cts.Dispose();
                }
            });
        }

        private async Task<string> NewProject(ApiClient api, BuildingModel model, Document doc, Brief brief, CancellationToken ct)
        {
            string id = await api.CreateProjectAsync(model.Project.Name, ct);
            brief.ProjectId = id;
            // Remember the project id in the model so re-checks update the same project.
            _ui.Post(_ =>
            {
                if (doc.IsValidObject && !doc.IsReadOnly)
                {
                    Brief current = BriefStore.Read(doc);
                    current.ProjectId = id;
                    BriefStore.Write(doc, current);
                }
            });
            return id;
        }

        /// <summary>Main thread (ExternalEvent): show results and colour the Compliance Check view.</summary>
        private void Apply(UIApplication app, string docKey, CheckReport report, IReadOnlyList<string> warnings)
        {
            _lastReport.TryGetValue(docKey, out CheckReport? previous);
            _lastReport[docKey] = report;
            var view = new ReportView(report, previous);
            _pane.Show(view, warnings);
            app.GetDockablePane(App.ResultsPaneId).Show();

            Document? doc = app.ActiveUIDocument?.Document;
            if (doc is not null && string.Equals(docKey, string.IsNullOrEmpty(doc.PathName) ? doc.Title : doc.PathName, StringComparison.OrdinalIgnoreCase))
            {
                View3D v = ComplianceView.Apply(doc, view);
                app.ActiveUIDocument!.RequestViewChange(v);
            }
        }

        public void Dispose()
        {
            _running?.Cancel();
            _ui.Dispose();
        }
    }
}
