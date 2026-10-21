using System;
using System.IO;

namespace ComplianceChecker.AutoCAD
{
    /// <summary>
    /// A plain log at %AppData%\ComplianceChecker\autocad.log: each command's steps and any error with
    /// its stack trace, so problems inside AutoCAD can be diagnosed without a debugger.
    /// </summary>
    internal static class Log
    {
        public static readonly string FilePath = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData), "ComplianceChecker", "autocad.log");

        public static void Info(string message) => Write("INFO ", message);

        public static void Error(string where, Exception e) => Write("ERROR", $"{where}: {e}");

        private static void Write(string level, string message)
        {
            try
            {
                Directory.CreateDirectory(Path.GetDirectoryName(FilePath)!);
                File.AppendAllText(FilePath, $"{DateTime.Now:yyyy-MM-dd HH:mm:ss} {level} {message}{Environment.NewLine}");
            }
            catch (Exception)
            {
                // logging must never break a command
            }
        }
    }
}
