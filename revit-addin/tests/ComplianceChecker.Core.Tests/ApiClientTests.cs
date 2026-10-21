using System.Net;
using System.Text;
using ComplianceChecker.Core.Api;
using ComplianceChecker.Core.Model;

namespace ComplianceChecker.Core.Tests;

public class ApiClientTests
{
    /// <summary>Records requests and replies with canned responses.</summary>
    private sealed class FakeHandler : HttpMessageHandler
    {
        private readonly Func<HttpRequestMessage, HttpResponseMessage> _reply;
        public List<(HttpRequestMessage Req, string? Body)> Seen { get; } = new();

        public FakeHandler(Func<HttpRequestMessage, HttpResponseMessage> reply) => _reply = reply;

        protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken ct)
        {
            Seen.Add((request, request.Content is null ? null : await request.Content.ReadAsStringAsync(ct)));
            return _reply(request);
        }
    }

    private static HttpResponseMessage Json(string body, HttpStatusCode code = HttpStatusCode.OK) =>
        new(code) { Content = new StringContent(body, Encoding.UTF8, "application/json") };

    [Fact]
    public async Task Pairing_posts_code_and_returns_token()
    {
        var h = new FakeHandler(_ => Json("{\"token\":\"tok-123\"}"));
        var api = new ApiClient("http://server:8000/", null, new HttpClient(h));
        Assert.Equal("tok-123", await api.CompletePairingAsync("123456", "PC-1"));
        var (req, body) = h.Seen.Single();
        Assert.Equal("http://server:8000/api/pair/complete", req.RequestUri!.ToString());
        Assert.Equal("{\"code\":\"123456\",\"device\":\"PC-1\"}", body);
    }

    [Fact]
    public async Task Drawing_upload_posts_raw_dxf_and_reads_layers()
    {
        const string reply = "{\"model_version\":\"v2\",\"warnings\":[\"w\"],\"counts\":{\"spaces\":14},"
            + "\"has_site_boundary\":true,\"unmapped\":1,"
            + "\"layers\":[{\"layer\":\"_Room\",\"role\":\"room\",\"source\":\"predcr\",\"entities\":14},"
            + "{\"layer\":\"MYSTERY\",\"role\":null,\"source\":null,\"entities\":3}]}";
        var h = new FakeHandler(_ => Json(reply));
        var api = new ApiClient("http://server:8000", "secret", new HttpClient(h));
        DrawingUpload up = await api.UploadDxfAsync("p1", Encoding.ASCII.GetBytes("  0\nSECTION"));
        Assert.Equal("v2", up.ModelVersion);
        Assert.Equal(14, up.Counts!["spaces"]);
        Assert.Equal(1, up.Unmapped);
        Assert.Null(up.Layers![1].Role);
        var (req, body) = h.Seen.Single();
        Assert.Equal(HttpMethod.Post, req.Method);
        Assert.Equal("http://server:8000/api/projects/p1/dxf", req.RequestUri!.ToString());
        Assert.Equal("  0\nSECTION", body);

        await api.SetLayerRolesAsync("p1", new Dictionary<string, string> { ["MYSTERY"] = "ignore" });
        Assert.Equal(HttpMethod.Put, h.Seen[1].Req.Method);
        Assert.Equal("{\"MYSTERY\":\"ignore\"}", h.Seen[1].Body);
    }

    [Fact]
    public async Task Calls_send_the_bearer_token_and_model_json()
    {
        var h = new FakeHandler(r => r.Method == HttpMethod.Put ? Json("{\"model_version\":\"v1\"}") : Json("{\"job_id\":\"j1\"}"));
        var api = new ApiClient("http://server:8000", "secret", new HttpClient(h));
        var model = ModelBuilder.Build(ModelBuilderTests.House(), new Brief(), DateTimeOffset.UnixEpoch);
        Assert.Equal("v1", await api.PutModelAsync("p 1", model));
        Assert.Equal("j1", await api.StartCheckAsync("p 1"));
        Assert.All(h.Seen, s => Assert.Equal("Bearer secret", s.Req.Headers.Authorization!.ToString()));
        Assert.Equal("http://server:8000/api/projects/p%201/model", h.Seen[0].Req.RequestUri!.AbsoluteUri);
        Assert.Contains("\"schema_version\":\"1.0\"", h.Seen[0].Body);
    }

    [Fact]
    public async Task Errors_surface_the_server_detail()
    {
        var h = new FakeHandler(_ => Json("{\"detail\":\"pairing code expired\"}", HttpStatusCode.BadRequest));
        var api = new ApiClient("http://server:8000", null, new HttpClient(h));
        var e = await Assert.ThrowsAsync<ApiException>(() => api.CompletePairingAsync("000000", "PC"));
        Assert.Equal(400, e.Status);
        Assert.Equal("HTTP 400: pairing code expired", e.Message);
    }

    [Fact]
    public async Task Sse_stream_is_parsed_until_done()
    {
        const string stream =
            ": keep-alive\n\n" +
            "event: progress\ndata: {\"stage\":\"evaluate\",\"pct\":40,\"msg\":\"Checking 22 rules\"}\n\n" +
            "data: {\"stage\":\"freshness\",\"pct\":70}\n\n" +
            "data: {\"stage\":\"done\",\"pct\":100,\"report_id\":\"r9\"}\n\n" +
            "data: {\"stage\":\"ignored-after-done\"}\n\n";
        var h = new FakeHandler(_ => new HttpResponseMessage(HttpStatusCode.OK)
        {
            Content = new StringContent(stream, Encoding.UTF8, "text/event-stream"),
        });
        var api = new ApiClient("http://server:8000", "t", new HttpClient(h));
        var events = new List<JobEvent>();
        await foreach (var e in api.StreamJobAsync("j1"))
            events.Add(e);
        Assert.Equal(new[] { "evaluate", "freshness", "done" }, events.Select(e => e.Stage));
        Assert.Equal("Checking 22 rules", events[0].Msg);
        Assert.Equal("r9", events[^1].ReportId);
        Assert.True(events[^1].IsFinal);
    }

    [Fact]
    public async Task Report_parses_into_the_generated_contract()
    {
        string golden = File.ReadAllText(Path.Combine(ModelBuilderTests.RepoRoot(), "fixtures", "expected", "violating_apartment.report.json"));
        var h = new FakeHandler(_ => Json(golden));
        var api = new ApiClient("http://server:8000", "t", new HttpClient(h));
        var report = await api.GetReportAsync("r1");
        Assert.Equal(13, report.Summary.Fail);
        Assert.Contains(report.Results, r => r.RuleId == "pmc.tod.max-fsi" && r.FixBy is { Amount: 0.7 });
    }
}
