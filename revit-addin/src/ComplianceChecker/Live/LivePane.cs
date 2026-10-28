using Autodesk.Revit.UI;
using ComplianceChecker.UI;

namespace ComplianceChecker.Live
{
    /// <summary>The live panel as a Revit dockable pane, docked on the left beside the model.</summary>
    internal sealed class LivePane : IDockablePaneProvider
    {
        public LiveGauge Gauge { get; } = new();

        public void SetupDockablePane(DockablePaneProviderData data)
        {
            data.FrameworkElement = Gauge;
            data.InitialState = new DockablePaneState { DockPosition = DockPosition.Left, MinimumWidth = 250 };
        }
    }
}
