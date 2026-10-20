using ComplianceChecker.Core.Results;
using ComplianceChecker.Generated;

namespace ComplianceChecker.Core.Tests;

public class ReportViewTests
{
    private static CheckReport Golden(string name) =>
        CheckReport.FromJson(File.ReadAllText(Path.Combine(ModelBuilderTests.RepoRoot(), "fixtures", "expected", name + ".report.json")));

    [Fact]
    public void Groups_fails_first_then_unverifiable_and_summarises()
    {
        var view = new ReportView(Golden("violating_apartment"));
        Assert.Equal(Status.Fail, view.Groups[0].Status);
        Assert.Equal(13, view.Groups[0].Rows.Count);
        Assert.Equal(Severity.Critical, view.Groups[0].Rows[0].Severity);
        Assert.StartsWith("13 fail · 0 cannot verify · 1 advisory", view.SummaryLine);
        Assert.Null(view.DiffLine); // no previous run
    }

    [Fact]
    public void Rows_carry_clause_values_fix_and_facts()
    {
        var view = new ReportView(Golden("violating_apartment"));
        var fsi = view.Groups[0].Rows.Single(r => r.RuleId == "pmc.tod.max-fsi");
        Assert.Equal("14.2.1.2", fsi.ClauseRef);
        Assert.Equal("udcpr2020 p.266", fsi.ClauseSource);
        Assert.Equal("3.2", fsi.Measured);
        Assert.Equal("2.5", fsi.Limit);
        Assert.Equal("Decrease by 0.7 FSI", fsi.Fix);
        Assert.Contains(fsi.Facts, f => f.StartsWith("site.edges[e1].road_width_m = 10.5 (declared)"));
        Assert.True(fsi.IsDraftRule);
    }

    [Fact]
    public void Fsi_line_reports_overage_in_square_metres()
    {
        var view = new ReportView(Golden("violating_apartment"));
        Assert.Equal("FSI 3.20 used · basic 1.10 · max 2.50 · 700 sq.m over the maximum", view.FsiLine);
        Assert.Equal("FSI 0.63 used · basic 1.10 · max 2.00 · 411 sq.m still buildable", new ReportView(Golden("compliant_house")).FsiLine);
        Assert.StartsWith("FSI: can't be calculated yet — needs", new ReportView(Golden("missing_site")).FsiLine);
    }

    [Fact]
    public void Element_status_takes_the_worst_result_per_element()
    {
        var view = new ReportView(Golden("violating_apartment"));
        Assert.Equal(Status.Fail, view.ElementStatus["fx-st-1"]);  // stair: width, riser, tread all fail
        Assert.Equal(Status.Pass, view.ElementStatus["fx-sp-5"]);  // toilet height passes
        Assert.False(view.ElementStatus.ContainsKey("fx-un-6"));   // shop unit: only not-applicable rules
    }

    [Fact]
    public void Diff_marks_fixed_and_new_failures()
    {
        CheckReport before = Golden("violating_apartment");
        CheckReport after = Golden("violating_apartment");
        // The stair is widened: its width check now passes. A new door failure appears.
        var stair = after.Results.Single(r => r.RuleId == "udcpr2020.ch9.stair-width-residential");
        stair.Status = Status.Pass;
        var door = after.Results.First(r => r.RuleId == "udcpr2020.ch9.exit-door-width" && r.Status != Status.Fail);
        door.Status = Status.Fail;

        var view = new ReportView(after, before);
        var rows = view.Groups.SelectMany(g => g.Rows).ToList();
        Assert.Equal(Change.Fixed, rows.Single(r => r.RuleId == "udcpr2020.ch9.stair-width-residential").Change);
        Assert.Equal(Change.New, rows.Single(r => r.RuleId == door.RuleId && r.ElementId == door.Element.Id).Change);
        Assert.Equal("Since last run: 1 fixed · 1 new failure", view.DiffLine);
    }

    [Theory]
    [InlineData(0.05, "m", FixDirection.Increase, "Increase by 0.05 m")]
    [InlineData(3.0, "m2", FixDirection.Increase, "Increase by 3 sq.m")]
    [InlineData(0.44, null, FixDirection.Increase, "Increase by 0.44")]
    public void Fix_text(double amount, string? unit, FixDirection dir, string expected) =>
        Assert.Equal(expected, ReportView.FixText(new FixBy { Amount = amount, Unit = unit, Direction = dir }));
}
