using Autodesk.AutoCAD.Runtime;
using Autodesk.Windows;

[assembly: ExtensionApplication(typeof(ComplianceChecker.AutoCAD.App))]
[assembly: CommandClass(typeof(ComplianceChecker.AutoCAD.Commands))]

namespace ComplianceChecker.AutoCAD
{
    /// <summary>Plug-in entry: adds the Compliance ribbon tab once AutoCAD's ribbon exists.</summary>
    public sealed class App : IExtensionApplication
    {
        public void Initialize()
        {
            if (ComponentManager.Ribbon is not null)
                Ribbon.Build();
            else
                ComponentManager.ItemInitialized += OnRibbonReady;
        }

        private static void OnRibbonReady(object? sender, RibbonItemEventArgs e)
        {
            if (ComponentManager.Ribbon is null)
                return;
            ComponentManager.ItemInitialized -= OnRibbonReady;
            Ribbon.Build();
        }

        public void Terminate() => Highlighter.Clear();
    }
}
