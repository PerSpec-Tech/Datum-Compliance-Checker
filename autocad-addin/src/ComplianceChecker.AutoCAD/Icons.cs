using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using System.Windows.Shapes;

namespace ComplianceChecker.AutoCAD
{
    /// <summary>The web app's line icons (20×20 paths), for the ribbon and the palettes.</summary>
    internal static class Icons
    {
        public const string Plug = "M7 2v4M13 2v4M5 6h10v3a5 5 0 0 1-10 0V6zM10 14v4";
        public const string Layers = "M10 3l7 4-7 4-7-4 7-4zM3 11l7 4 7-4";
        public const string Pin = "M10 18s5-5.2 5-9a5 5 0 0 0-10 0c0 3.8 5 9 5 9zM10 10.5a1.5 1.5 0 1 0 0-3 1.5 1.5 0 0 0 0 3z";
        public const string Check = "M4 10.5l3.5 3.5L16 5.5";
        public const string Cross = "M5 5l10 10M15 5L5 15";
        public const string Question = "M7.5 7.5a2.5 2.5 0 1 1 3.5 2.3c-.6.3-1 .8-1 1.5v.7M10 14.5v.5M10 2.5a7.5 7.5 0 1 0 0 15 7.5 7.5 0 0 0 0-15z";
        public const string List = "M7 5h10M7 10h10M7 15h10M3 5h.5M3 10h.5M3 15h.5";
        public const string Book = "M4 3h9a3 3 0 0 1 3 3v11H7a3 3 0 0 1-3-3V3zM4 14a3 3 0 0 1 3-3h9";
        public const string Refresh = "M16 10a6 6 0 1 1-1.8-4.3M16 3v3.5h-3.5";
        public const string Eye = "M2 10s3-5.5 8-5.5 8 5.5 8 5.5-3 5.5-8 5.5S2 10 2 10zM10 12.5a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5z";

        public static readonly Brush Grey = Frozen(Color.FromRgb(0x9a, 0x9a, 0xa1));
        public static readonly Brush Red = Frozen(Color.FromRgb(0xf5, 0x45, 0x5c));
        public static readonly Brush Green = Frozen(Color.FromRgb(0x3e, 0xd5, 0x98));

        public static ImageSource Image(string path, int size, Brush? brush = null)
        {
            var pen = new Pen(brush ?? Grey, 1.6) { StartLineCap = PenLineCap.Square, EndLineCap = PenLineCap.Square };
            var drawing = new DrawingGroup();
            drawing.Children.Add(new GeometryDrawing(Brushes.Transparent, null, new RectangleGeometry(new Rect(0, 0, 20, 20))));
            drawing.Children.Add(new GeometryDrawing(null, pen, Geometry.Parse(path)));
            var image = new DrawingImage(drawing);
            image.Freeze();
            return image;
        }

        /// <summary>An icon as a WPF element, for buttons and list rows.</summary>
        public static FrameworkElement Glyph(string path, double size = 14, Brush? brush = null) =>
            new Path
            {
                Data = Geometry.Parse(path),
                Stroke = brush ?? Grey,
                StrokeThickness = 1.6,
                Width = size,
                Height = size,
                Stretch = Stretch.Uniform,
                VerticalAlignment = VerticalAlignment.Center,
            };

        /// <summary>A button with an icon and a label.</summary>
        public static Button Button(string path, string text, RoutedEventHandler onClick)
        {
            var row = new StackPanel { Orientation = Orientation.Horizontal };
            row.Children.Add(Glyph(path, 14));
            row.Children.Add(new TextBlock { Text = text, Margin = new Thickness(6, 0, 0, 0), VerticalAlignment = VerticalAlignment.Center });
            var b = new Button { Content = row, Padding = new Thickness(8, 4, 8, 4), Margin = new Thickness(0, 0, 6, 0) };
            b.Click += onClick;
            return b;
        }

        private static Brush Frozen(Color c)
        {
            var b = new SolidColorBrush(c);
            b.Freeze();
            return b;
        }
    }
}
