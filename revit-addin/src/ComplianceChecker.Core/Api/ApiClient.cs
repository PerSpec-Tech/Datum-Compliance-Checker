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

    /// <summary>Upload a 2D drawing as DXF (AutoCAD plug-in, P11): the server reads it with the same
    /// reader as the web app. Returns what was read and every layer's role.</summary>
    public async Task<DrawingUpload> UploadDxfAsync(string projectId, byte[] dxf, CancellationToken ct = default)
    {
        using var req = Request(HttpMethod.Post, $"api/projects/{Uri.EscapeDataString(projectId)}/dxf");
        req.Content = new ByteArrayContent(dxf);
        req.Content.Headers.ContentType = new MediaTypeHeaderValue("application/dxf");
        return await ReadAsync<DrawingUpload>(await _http.SendAsync(req, ct), ct);
    }

    /// <summary>Set layer → role for the drawing ("ignore" to leave a layer out); re-reads it.</summary>
    public Task<DrawingUpload> SetLayerRolesAsync(string projectId, IReadOnlyDictionary<string, string> roles, CancellationToken ct = default) =>
        SendAsync<DrawingUpload>(HttpMethod.Put, $"api/projects/{Uri.EscapeDataString(projectId)}/dxf/roles", roles, ct);

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

    /// <summary>The project's latest model with the brief merged in, as raw JSON
    /// ({model_version, model, skipped_answers}); the AutoCAD plug-in reads plot sides from it.</summary>
    public async Task<string> GetModelJsonAsync(string projectId, CancellationToken ct = default)
    {
        using var req = Request(HttpMethod.Get, $"api/projects/{Uri.EscapeDataString(projectId)}/model");
        using var resp = await _http.SendAsync(req, ct);
        await EnsureOk(resp, ct);
        return await resp.Content.ReadAsStringAsync(ct);
    }

    /// <summary>Where each floor plan of the uploaded drawing sits and how it was moved into plot
    /// coordinates, plus the layer roles (GET /drawing/frames; AutoCAD live mode, P11.4).</summary>
    public Task<DrawingFrames> GetDrawingFramesAsync(string projectId, CancellationToken ct = default) =>
        SendAsync<DrawingFrames>(HttpMethod.Get, $"api/projects/{Uri.EscapeDataString(projectId)}/drawing/frames", null, ct);

    /// <summary>Declare facts for the next check (PATCH /brief): path → value, e.g.
    /// "project.location" → {lat, lon}, "site.boundary" → [[x, y], …], "site.edges" → {e1: {kind, road_width_m}}.</summary>
    public Task<JsonElement> PatchBriefAsync(string projectId, IReadOnlyDictionary<string, object?> answers, CancellationToken ct = default) =>
        SendAsync<JsonElement>(HttpMethod.Patch, $"api/projects/{Uri.EscapeDataString(projectId)}/brief", answers, ct);

    /// <summary>Places in the authority's area for an address (GET /geocode).</summary>
    public async Task<IReadOnlyList<Place>> GeocodeAsync(string query, string authority = "pmc", CancellationToken ct = default) =>
        await SendAsync<List<Place>>(HttpMethod.Get, $"api/geocode?q={Uri.EscapeDataString(query)}&authority={Uri.EscapeDataString(authority)}", null, ct);

    /// <summary>Address suggestions as you type (GET /suggest): addresses are Precise, areas are not.</summary>
    public async Task<IReadOnlyList<PlaceSuggestion>> SuggestAsync(string query, string authority = "pmc", CancellationToken ct = default) =>
        await SendAsync<List<PlaceSuggestion>>(HttpMethod.Get, $"api/suggest?q={Uri.EscapeDataString(query)}&authority={Uri.EscapeDataString(authority)}", null, ct);

    /// <summary>Which authority covers a point, and a short place name (GET /locate).</summary>
    public Task<Located> LocateAsync(double lat, double lon, CancellationToken ct = default) =>
        SendAsync<Located>(HttpMethod.Get, FormattableString.Invariant($"api/locate?lat={lat}&lon={lon}"), null, ct);

    /// <summary>Planning facts the server suggests (occupancy, building type, congested area, land use).</summary>
    public async Task<IReadOnlyList<Suggestion>> GetSuggestionsAsync(string projectId, double lat, double lon, CancellationToken ct = default) =>
        await SendAsync<List<Suggestion>>(HttpMethod.Get,
            FormattableString.Invariant($"api/projects/{Uri.EscapeDataString(projectId)}/suggestions?lat={lat}&lon={lon}"), null, ct);

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

    /// <summary>The latest check's live pack (P9.1); null if the project has no check yet.</summary>
    public async Task<Live.LivePack?> GetLivePackAsync(string projectId, CancellationToken ct = default)
    {
        using var req = Request(HttpMethod.Get, $"api/projects/{projectId}/live-pack");
        using HttpResponseMessage resp = await _http.SendAsync(req, ct);
        if (resp.StatusCode == System.Net.HttpStatusCode.NotFound)
            return null;
        resp.EnsureSuccessStatusCode();
        return Live.LivePack.FromJson(await resp.Content.ReadAsStringAsync(ct));
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

public sealed record Place(string Label, double Lat, double Lon);

/// <summary>An address suggestion: a precise place (address, street) or an area (its centre).</summary>
public sealed record PlaceSuggestion(string Label, double Lat, double Lon, string? Kind = null, bool Precise = true);

public sealed record Located(string? AuthorityId, string? Note, string? Label);

/// <summary>A suggested planning fact and what the model has now (facts as raw JSON: {value, source, note}).</summary>
public sealed record Suggestion(string Path, JsonElement Suggested, JsonElement Current);

/// <summary>What the server read from an uploaded drawing (POST /dxf, PUT /dxf/roles).</summary>
public sealed record DrawingUpload(
    string? ModelVersion = null,
    IReadOnlyList<string>? Warnings = null,
    IReadOnlyDictionary<string, int>? Counts = null,
    bool HasSiteBoundary = false,
    IReadOnlyList<LayerRole>? Layers = null,
    int Unmapped = 0);

/// <summary>A drawing's floor plans: a point (x, y) of the drawing inside a floor's bounds is at
/// (x * Scale + Shift[0], y * Scale + Shift[1]) in the model (metres, plot coordinates).</summary>
public sealed record DrawingFrames(double Scale, IReadOnlyDictionary<string, string> Roles, IReadOnlyList<FloorFrame> Floors);

/// <summary>One floor plan: its name, the floor numbers it stands for (a typical plan stands for several),
/// its frame in drawing units [x0, y0, x1, y1] and its shift in metres.</summary>
public sealed record FloorFrame(string? Name, IReadOnlyList<int> Nums, double[] Bounds, double[] Shift);

/// <summary>One layer of the drawing: its role (null = not understood) and where the role came from
/// (predcr, user, suggested by Nemotron, or convention).</summary>
public sealed record LayerRole(string Layer, string? Role, string? Source = null, double? Confidence = null, int Entities = 0);

public sealed class ApiException : Exception
{
    public int Status { get; }

    public ApiException(int status, string message) : base(status > 0 ? $"HTTP {status}: {message}" : message) => Status = status;
}
