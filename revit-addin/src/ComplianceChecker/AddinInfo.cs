using System.Reflection;

namespace ComplianceChecker
{
    internal static class AddinInfo
    {
        public static string Version =>
            "ComplianceChecker " + (Assembly.GetExecutingAssembly().GetName().Version?.ToString(3) ?? "0.0.0");
    }
}
