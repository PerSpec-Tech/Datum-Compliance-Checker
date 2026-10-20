using System.Net.Http.Headers;
using System.Runtime.CompilerServices;
using System.Text;
using System.Text.Json;
using System.Text.Json.Serialization;
using ComplianceChecker.Generated;

namespace ComplianceChecker.Core.Api;

/// <summary>
/// HTTP client for the backend API (ROADMAP §5.5). One shared HttpClient (P5.5). All calls are async
/// and must run off Revit's UI thread; results go back through an ExternalEvent (P5.6).
/// </summary>
public sealed class ApiClient
{
    private static readonly HttpClient Shared = new() { Timeout = TimeSpan.FromMinutes(5) };
    private static readonly JsonSerializerOptions Json = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
        DefaultIgnoreCondition = JsonIgnoreCondition.WhenWritingNull,
    };

    private readonly HttpClient _http;
    private readonly Uri _base;
    private readonly string? _token;

    public ApiClient(string baseUrl, string? token, HttpClient? http = null)
    {
        _base = new Uri(baseUrl.TrimEnd('/') + "/");
        _token = token;
        _http = http ?? Shared;
    }

    /// <summary>Exchange the 6-digit code shown in the web app for a bearer token.</summary>
    public async Task<string> CompletePairingAsync(string code, string device, CancellationToken ct = default)
    {
        var r = await SendAsync<TokenResponse>(HttpMethod.Post, "api/pair/complete", new { code, device }, ct);
        return r.Token ?? throw new ApiException(0, "server returned no token");
    }

    public async Task<string> CreateProjectAsync(string name, CancellationToken ct = default) =>
        (await SendAsync<IdResponse>(HttpMethod.Post, "api/projects", new { name }, ct)).Id
        ?? throw new ApiException(0, "server returned no project id");

    /// <summary>Upload the BuildingModel (contract JSON). Returns the server's model version id.</summary>
    public async Task<string?> PutModelAsync(string projectId, BuildingModel model, CancellationToken ct = default)
    {
        using var req = Request(HttpMethod.Put, $"api/projects/{Uri.EscapeDataString(projectId)}/model");
        req.Content = new StringContent(model.ToJson(), Encoding.UTF8, "application/json");
        return (await ReadAsync<ModelVersionResponse>(await _http.SendAsync(req, ct), ct)).ModelVersion;
    }

    public async Task<string> StartCheckAsync(string projectId, CancellationToken ct = default) =>
        (await SendAsync<JobResponse>(HttpMethod.Post, $"api/projects/{Uri.EscapeDataString(projectId)}/checks", null, ct)).JobId
        ?? throw new ApiException(0, "server returned no job id");

    /// <summary>Stream job progress (server-sent events) until the job is done or fails.</summary>
    public async IAsyncEnumerable<JobEvent> StreamJobAsync(string jobId, [EnumeratorCancellation] CancellationToken ct = default)
    {
        using var req = Request(HttpMethod.Get, $"api/jobs/{Uri.EscapeDataString(jobId)}/events");
        req.Headers.Accept.Add(new MediaTypeWithQualityHeaderValue("text/event-stream"));
        using var resp = await _http.SendAsync(req, HttpCompletionOption.ResponseHeadersRead, ct);
        await EnsureOk(resp, ct);
        using var reader = new StreamReader(await resp.Content.ReadAsStreamAsync(ct));
        await foreach (JobEvent e in ParseSse(reader, ct))
        {
            yield return e;
            if (e.IsFinal)
                yield break;
        }
    }

    public async Task<CheckReport> GetReportAsync(string reportId, CancellationToken ct = default)
    {
        using var req = Request(HttpMethod.Get, $"api/reports/{Uri.EscapeDataString(reportId)}");
        using var resp = await _http.SendAsync(req, ct);
        await EnsureOk(resp, ct);
        return CheckReport.FromJson(await resp.Content.ReadAsStringAsync(ct));
    }

    // ------------------------------------------------------------------ internals

    internal static async IAsyncEnumerable<JobEvent> ParseSse(TextReader reader, [EnumeratorCancellation] CancellationToken ct)
    {
        var data = new StringBuilder();
        string? line;
        while ((line = await reader.ReadLineAsync(ct)) is not null)
        {
            if (line.StartsWith("data:", StringComparison.Ordinal))
            {
                data.Append(line.AsSpan(5).TrimStart());
            }
            else if (line.Length == 0 && data.Length > 0)
            {
                JobEvent? e = JsonSerializer.Deserialize<JobEvent>(data.ToString(), Json);
                data.Clear();
                if (e is not null)
                    yield return e;
            }
            // other SSE fields (event:, id:, retry:, comments) are ignored
        }
        if (data.Length > 0 && JsonSerializer.Deserialize<JobEvent>(data.ToString(), Json) is { } last)
            yield return last;
    }

    private HttpRequestMessage Request(HttpMethod method, string path)
    {
        var req = new HttpRequestMessage(method, new Uri(_base, path));
        if (!string.IsNullOrEmpty(_token))
            req.Headers.Authorization = new AuthenticationHeaderValue("Bearer", _token);
        return req;
    }

    private async Task<T> SendAsync<T>(HttpMethod method, string path, object? body, CancellationToken ct)
    {
        using var req = Request(method, path);
        if (body is not null)
            req.Content = new StringContent(JsonSerializer.Serialize(body, Json), Encoding.UTF8, "application/json");
        return await ReadAsync<T>(await _http.SendAsync(req, ct), ct);
    }

    private static async Task<T> ReadAsync<T>(HttpResponseMessage resp, CancellationToken ct)
    {
        using (resp)
        {
            await EnsureOk(resp, ct);
            string text = await resp.Content.ReadAsStringAsync(ct);
            return JsonSerializer.Deserialize<T>(string.IsNullOrWhiteSpace(text) ? "{}" : text, Json)
                   ?? throw new ApiException((int)resp.StatusCode, "empty response");
        }
    }

    private static async Task EnsureOk(HttpResponseMessage resp, CancellationToken ct)
    {
        if (resp.IsSuccessStatusCode)
            return;
        string body = await resp.Content.ReadAsStringAsync(ct);
        string detail = body;
        try
        {
            using var doc = JsonDocument.Parse(body);
            if (doc.RootElement.TryGetProperty("detail", out var d))
                detail = d.ValueKind == JsonValueKind.String ? d.GetString()! : d.ToString();
        }
        catch (JsonException)
        {
            // not JSON: keep the raw body
        }
        throw new ApiException((int)resp.StatusCode, detail.Length > 300 ? detail[..300] : detail);
    }

    private sealed record TokenResponse(string? Token);
    private sealed record IdResponse(string? Id);
    private sealed record JobResponse(string? JobId);
    private sealed record ModelVersionResponse(string? ModelVersion);
}

/// <summary>One progress event of a check job: {stage, pct, msg} … {stage: "done", report_id}.</summary>
public sealed record JobEvent(string Stage, double? Pct = null, string? Msg = null, string? ReportId = null, string? Error = null)
{
    public bool IsFinal => Stage is "done" or "error";
}

public sealed class ApiException : Exception
{
    public int Status { get; }

    public ApiException(int status, string message) : base(status > 0 ? $"HTTP {status}: {message}" : message) => Status = status;
}
