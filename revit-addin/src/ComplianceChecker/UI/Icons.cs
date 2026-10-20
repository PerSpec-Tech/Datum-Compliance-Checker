using System.Globalization;
using System.Windows;
using System.Windows.Media;
using System.Windows.Media.Imaging;

namespace ComplianceChecker.UI
{
    /// <summary>Ribbon icons drawn at runtime (a coloured tile with a glyph), so no image files ship.</summary>
    internal static class Icons
    {
        public static BitmapSource Create(string glyph, Color color, int size)
        {
            var visual = new DrawingVisual();
            using (DrawingContext dc = visual.RenderOpen())
            {
                double r = size / 6.0;
                dc.DrawRoundedRectangle(new SolidColorBrush(color), null, new Rect(1, 1, size - 2, size - 2), r, r);
                var text = new FormattedText(glyph, CultureInfo.InvariantCulture, FlowDirection.LeftToRight,
                    new Typeface(new FontFamily("Segoe UI"), FontStyles.Normal, FontWeights.Bold, FontStretches.Normal),
                    size * 0.62, Brushes.White, 1.0);
                dc.DrawText(text, new Point((size - text.Width) / 2, (size - text.Height) / 2));
            }
            var bitmap = new RenderTargetBitmap(size, size, 96, 96, PixelFormats.Pbgra32);
            bitmap.Render(visual);
            bitmap.Freeze();
            return bitmap;
        }
    }
}
