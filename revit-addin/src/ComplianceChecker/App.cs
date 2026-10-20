using System;
using Autodesk.Revit.UI;
using ComplianceChecker.Results;
using ComplianceChecker.UI;

namespace ComplianceChecker
{
    /// <summary>Revit entry point: builds the "Compliance" ribbon tab and registers the results pane.</summary>
    public class App : IExternalApplication
    {
        public static readonly DockablePaneId ResultsPaneId = new(new Guid("2f8f4c61-0d2a-4f3b-9a8e-5b1f6c7d9e21"));

        /// <summary>Set in OnStartup; commands use it to reach shared services.</summary>
        public static App? Current { get; private set; }

        public ResultsPane ResultsPane { get; private set; } = null!;
        public CheckRunner CheckRunner { get; private set; } = null!;

        public Result OnStartup(UIControlledApplication application)
        {
            Current = this;
            Ribbon.Build(application);

            // The ExternalEvent must be created here, in a valid API context.
            var ui = new UiActionQueue();
            ResultsPane = new ResultsPane();
            ResultsPane.Attach(ui);
            application.RegisterDockablePane(ResultsPaneId, "Compliance results", ResultsPane);
            CheckRunner = new CheckRunner(ResultsPane, ui);
            return Result.Succeeded;
        }

        public Result OnShutdown(UIControlledApplication application)
        {
            CheckRunner?.Dispose();
            return Result.Succeeded;
        }
    }
}
