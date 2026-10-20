using System.Globalization;
using System.Text.Json;
using ComplianceChecker.Generated;

namespace ComplianceChecker.Core.Results;

public enum Change { None, New, Fixed }

/// <summary>One result as the panel shows it (P5.7). Plain strings: no Revit or WPF types.</summary>
public sealed record ResultRow(
    string RuleId,
    string Title,
    Status Status,
    Severity Severity,
    string? ElementKind,
    string? ElementId,
    string? SourceId,
    string Message,
    string ClauseRef,
    string ClauseExcerpt,
    string ClauseSource,
    string? Measured,
    string? Limit,
    string? Fix,
    IReadOnlyList<string> Facts,
    IReadOnlyList<string> MissingInputs,
    bool IsDraftRule,
    bool PossiblySuperseded,
    string? FreshnessUrl,
    Change Change)
{
    public string Key => ReportView.Key(RuleId, SourceId ?? ElementId);
}

public sealed record ResultGroup(Status Status, string Title, IReadOnlyList<ResultRow> Rows);

/// <summary>Turns a CheckReport (+ the previous one) into what the results panel shows (P5.7, P5.9).</summary>
public sealed class ReportView
{
    private static readonly (Status Status, string Title)[] Order =
    {
        (Status.Fail, "Fails"),
        (Status.Unverifiable, "Cannot verify"),
        (Status.Advisory, "Advisories"),
        (Status.Pass, "Passes"),
        (Status.NotApplicable, "Not applicable"),
    };

    public IReadOnlyList<ResultGroup> Groups { get; }
    public string SummaryLine { get; }
    public string? FsiLine { get; }
    public string? DiffLine { get; }
    public IReadOnlyList<Question> Questions { get; }
    public string? Explanation { get; }

    /// <summary>Worst status per model element (source_id), for colouring the Compliance view (P5.8).</summary>
    public IReadOnlyDictionary<string, Status> ElementStatus { get; }

    public ReportView(CheckReport report, CheckReport? previous = null)
    {
        var before = previous?.Results.ToDictionary(r => Key(r.RuleId, r.Element?.SourceId ?? r.Element?.Id), r => r.Status)
                     ?? new Dictionary<string, Status>();
        var rows = report.Results.Select(r => ToRow(r, previous is null ? Change.None : ChangeOf(r, before))).ToList();

        Groups = Order
            .Select(o => new ResultGroup(o.Status, o.Title, rows.Where(r => r.Status == o.Status)
                .OrderBy(r => r.Severity).ThenBy(r => r.RuleId, StringComparer.Ordinal).ThenBy(r => r.ElementId, StringComparer.Ordinal).ToList()))
            .Where(g => g.Rows.Count > 0)
            .ToList();

        Summary s = report.Summary;
        SummaryLine = $"{s.Fail} fail · {s.Unverifiable} cannot verify · {s.Advisory} advisory · {s.Pass} pass";
        FsiLine = report.Fsi is { } f ? FormatFsi(f) : null;
        Questions = report.Questions ?? new List<Question>();
        Explanation = report.Explanation;

        if (previous is not null)
        {
            int fixedCount = rows.Count(r => r.Change == Change.Fixed);
            int newCount = rows.Count(r => r.Change == Change.New);
            DiffLine = $"Since last run: {fixedCount} fixed · {newCount} new failure{(newCount == 1 ? "" : "s")}";
        }

        var worst = new Dictionary<string, Status>();
        foreach (var r in rows.Where(r => r.SourceId is not null))
        {
            int rank = Rank(r.Status);
            if (rank < 0)
                continue;
            if (!worst.TryGetValue(r.SourceId!, out var current) || rank > Rank(current))
                worst[r.SourceId!] = r.Status;
        }
        ElementStatus = worst;
    }

    public static string Key(string ruleId, string? element) => element is null ? ruleId : $"{ruleId}@{element}";

    /// <summary>fail &gt; cannot verify &gt; pass; other statuses don't colour elements.</summary>
    public static int Rank(Status s) => s switch { Status.Fail => 2, Status.Unverifiable => 1, Status.Pass => 0, _ => -1 };

    public static string? FixText(FixBy? fix)
    {
        if (fix is null)
            return null;
        string amount = fix.Amount.ToString("0.##", CultureInfo.InvariantCulture);
        string unit = fix.Unit switch { null or "" => "", "m2" => " sq.m", "FSI" => " FSI", var u => " " + u };
        return $"{(fix.Direction == FixDirection.Increase ? "Increase" : "Decrease")} by {amount}{unit}";
    }

    private static Change ChangeOf(Result r, Dictionary<string, Status> before)
    {
        string key = Key(r.RuleId, r.Element?.SourceId ?? r.Element?.Id);
        bool had = before.TryGetValue(key, out var was);
        if (r.Status == Status.Fail && (!had || was != Status.Fail))
            return Change.New;
        if (had && was == Status.Fail && r.Status == Status.Pass)
            return Change.Fixed;
        return Change.None;
    }

    private static ResultRow ToRow(Result r, Change change) => new(
        r.RuleId,
        r.Title,
        r.Status,
        r.Severity,
        r.Element?.Kind.ToString(),
        r.Element?.Id,
        r.Element?.SourceId,
        r.Message,
        r.Clause.Ref,
        r.Clause.Excerpt,
        r.Clause.Source,
        Scalar(r.Measured),
        Scalar(r.Limit),
        FixText(r.FixBy),
        (r.FactsUsed ?? new List<FactUsed>()).Select(f => $"{f.Path} = {FactValue(f.Value)} ({f.Source.ToString().ToLowerInvariant()})").ToList(),
        r.MissingInputs ?? new List<string>(),
        r.RuleStatus == RuleStatus.Draft,
        r.Freshness?.Status == FreshnessStatus.PossiblySuperseded,
        r.Freshness?.Url,
        change);

    private static string? Scalar(Value v) =>
        v.Double is double d ? d.ToString("0.###", CultureInfo.InvariantCulture)
        : v.Bool is bool b ? (b ? "yes" : "no")
        : v.String;

    private static string FactValue(object? value) => value switch
    {
        null => "unknown",
        JsonElement e => e.ValueKind == JsonValueKind.String ? e.GetString() ?? "" : e.ToString(),
        double d => d.ToString("0.###", CultureInfo.InvariantCulture),
        _ => Convert.ToString(value, CultureInfo.InvariantCulture) ?? "",
    };

    private static string FormatFsi(FsiSummary f)
    {
        static string N(double? v, string fmt = "0.00") => v?.ToString(fmt, CultureInfo.InvariantCulture) ?? "?";
        if (f.Used is null)
            return "FSI: can't be calculated yet — " + (f.MissingInputs.Count > 0 ? "needs " + string.Join(", ", f.MissingInputs.Take(3)) : "missing inputs");
        string head = $"FSI {N(f.Used)} used · basic {N(f.BasePermissible)} · max {N(f.MaxPermissible)}";
        string room = f.HeadroomMaxM2 is double h
            ? (h >= 0 ? $" · {h.ToString("0", CultureInfo.InvariantCulture)} sq.m still buildable" : $" · {(-h).ToString("0", CultureInfo.InvariantCulture)} sq.m over the maximum")
            : "";
        return head + room;
    }
}
