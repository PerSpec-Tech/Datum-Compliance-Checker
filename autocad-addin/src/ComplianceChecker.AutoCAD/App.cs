using System;
using Autodesk.AutoCAD.ApplicationServices;
using Autodesk.AutoCAD.Runtime;
using Autodesk.Windows;
using AcApp = Autodesk.AutoCAD.ApplicationServices.Application;

[assembly: ExtensionApplication(typeof(ComplianceChecker.AutoCAD.App))]
[assembly: CommandClass(typeof(ComplianceChecker.AutoCAD.Commands))]

namespace ComplianceChecker.AutoCAD
{
    /// <summary>
    /// Plug-in entry. The Compliance ribbon tab is added once AutoCAD is idle after start-up (the
    /// ribbon may not exist yet while plug-ins load), and again whenever the workspace changes,
    /// because switching or reloading a workspace rebuilds the ribbon without our tab.
    /// </summary>
    public sealed class App : IExtensionApplication
    {
        public void Initialize()
        {
            Log.Info("plug-in loaded");
            AcApp.Idle += OnFirstIdle;
            AcApp.SystemVariableChanged += OnSysVar;
        }

        private static void OnFirstIdle(object? sender, EventArgs e)
        {
            if (ComponentManager.Ribbon is null)
                return; // try again on the next idle
            AcApp.Idle -= OnFirstIdle;
            Ribbon.Build();
            Hello();
        }

        private static void OnSysVar(object? sender, SystemVariableChangedEventArgs e)
        {
            if (e.Name.Equals("WSCURRENT", StringComparison.OrdinalIgnoreCase))
                Ribbon.Build();
        }

        private static void Hello()
        {
            try
            {
                AcApp.DocumentManager.MdiActiveDocument?.Editor.WriteMessage(
                    "\nCompliance Checker loaded: Compliance tab on the ribbon (or type CCCHECK, CCPAIR, CCRIBBON).");
            }
            catch (System.Exception)
            {
                // no document open yet: the tab is enough
            }
        }

        public void Terminate()
        {
            AcApp.Idle -= OnFirstIdle;
            AcApp.SystemVariableChanged -= OnSysVar;
            Highlighter.Clear();
        }
    }
}
