using System;
using Autodesk.Revit.UI;
using ComplianceChecker.Live;
using ComplianceChecker.Results;
using ComplianceChecker.UI;

namespace ComplianceChecker
{
    /// <summary>Revit entry point: builds the "Compliance" ribbon tab and registers the results pane.</summary>
    public class App : IExternalApplication
    {
        public static readonly DockablePaneId ResultsPaneId = new(new Guid("2f8f4c61-0d2a-4f3b-9a8e-5b1f6c7d9e21"));
        public static readonly DockablePaneId LivePaneId = new(new Guid("8c1d0e52-3b7a-4f96-a2e4-71d5c9b0f348"));

        /// <summary>Set in OnStartup; commands use it to reach shared services.</summary>
        public static App? Current { get; private set; }

        public ResultsPane ResultsPane { get; private set; } = null!;
        public CheckRunner CheckRunner { get; private set; } = null!;
        internal LiveController Live { get; private set; } = null!;
        private LensServer _lens = null!;

        public Result OnStartup(UIControlledApplication application)
        {
            Current = this;
            Ribbon.Build(application);

            // The ExternalEvent must be created here, in a valid API context.
            var ui = new UiActionQueue();
            ResultsPane = new ResultsPane();
            ResultsPane.Attach(ui);
            application.RegisterDockablePane(ResultsPaneId, "Datum · results", ResultsPane);
            CheckRunner = new CheckRunner(ResultsPane, ui);

            // Live mode (P9.2/P9.3): the lens joins Revit's DirectContext3D service once Revit is up.
            _lens = new LensServer();
            var livePane = new LivePane();
            application.RegisterDockablePane(LivePaneId, "Datum · live", livePane);
            Live = new LiveController(ResultsPane, livePane.Gauge, _lens);
            Live.Hook(application);
            application.ControlledApplication.ApplicationInitialized += (_, _) => LensServer.Register(_lens);
            return Result.Succeeded;
        }

        public Result OnShutdown(UIControlledApplication application)
        {
            CheckRunner?.Dispose();
            Live?.Unhook(application);
            return Result.Succeeded;
        }
    }
}
