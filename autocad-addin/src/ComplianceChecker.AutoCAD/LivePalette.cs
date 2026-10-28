using System;
using Autodesk.AutoCAD.Windows;
using ComplianceChecker.Core.Live;
using ComplianceChecker.UI;

namespace ComplianceChecker.AutoCAD
{
    /// <summary>The live panel (FSI bar, height, setbacks) as a palette docked on the left of the drawing.</summary>
    internal static class LivePalette
    {
        private static PaletteSet? _set;
        private static readonly LiveGauge Gauge = new();

        public static void Show(LiveStatus status)
        {
            Ensure();
            Gauge.Show(status);
        }

        public static void Message(string text)
        {
            if (_set is null)
                return;
            Gauge.ShowMessage(text);
        }

        private static void Ensure()
        {
            if (_set is not null)
            {
                if (!_set.Visible)
                    _set.Visible = true;
                return;
            }
            _set = new PaletteSet("Datum · live", new Guid("b7e2c4a9-5d1f-4c63-8e0a-2f9d6b1c3a57"))
            {
                MinimumSize = new System.Drawing.Size(260, 420),
                Style = PaletteSetStyles.ShowCloseButton | PaletteSetStyles.ShowAutoHideButton,
            };
            _set.AddVisual("Live", Gauge);
            _set.KeepFocus = false;
            _set.Visible = true;
            try
            {
                _set.Dock = DockSides.Left;
            }
            catch (Exception e)
            {
                Log.Error("live palette dock", e); // floating is fine too
            }
        }
    }
}
