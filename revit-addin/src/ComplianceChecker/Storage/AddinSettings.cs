using System;
using System.IO;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;

namespace ComplianceChecker.Storage
{
    /// <summary>
    /// Per-user add-in settings in %AppData%\ComplianceChecker: settings.json (server URL) and
    /// token.bin (the pairing token, encrypted with Windows DPAPI for the current user — P5.5).
    /// </summary>
    public sealed class AddinSettings
    {
        public string ServerUrl { get; set; } = "http://localhost:8000";

        private static readonly string Folder =
            Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData), "ComplianceChecker");
        private static string SettingsFile => Path.Combine(Folder, "settings.json");
        private static string TokenFile => Path.Combine(Folder, "token.bin");
        private static readonly byte[] Entropy = Encoding.UTF8.GetBytes("ComplianceChecker.token.v1");
        private static readonly JsonSerializerOptions Json = new() { PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower, WriteIndented = true };

        public static AddinSettings Load()
        {
            try
            {
                return File.Exists(SettingsFile)
                    ? JsonSerializer.Deserialize<AddinSettings>(File.ReadAllText(SettingsFile), Json) ?? new AddinSettings()
                    : new AddinSettings();
            }
            catch (Exception)
            {
                return new AddinSettings(); // a corrupt settings file shouldn't break the add-in
            }
        }

        public void Save()
        {
            Directory.CreateDirectory(Folder);
            File.WriteAllText(SettingsFile, JsonSerializer.Serialize(this, Json));
        }

        public static string? LoadToken()
        {
            try
            {
                if (!File.Exists(TokenFile))
                    return null;
                byte[] plain = ProtectedData.Unprotect(File.ReadAllBytes(TokenFile), Entropy, DataProtectionScope.CurrentUser);
                return Encoding.UTF8.GetString(plain);
            }
            catch (CryptographicException)
            {
                return null; // token from another Windows user or machine: pair again
            }
        }

        public static void SaveToken(string token)
        {
            Directory.CreateDirectory(Folder);
            byte[] cipher = ProtectedData.Protect(Encoding.UTF8.GetBytes(token), Entropy, DataProtectionScope.CurrentUser);
            File.WriteAllBytes(TokenFile, cipher);
        }
    }
}
