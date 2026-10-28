using ComplianceChecker.Core.Api;
using ComplianceChecker.Core.Live;
using ComplianceChecker.Core.Model;
using Xunit;

namespace ComplianceChecker.Core.Tests;

/// <summary>AutoCAD live mode (P11.4): drawing polylines → plot coordinates, and FSI as a change.</summary>
public class DrawingLiveTests
{
    // Drawn in millimetres: a typical plan (floors 1–3) framed at x 100 000–130 000, moved 95 m west onto the plot.
    private static readonly DrawingFrames Frames = new(
        0.001,
        new Dictionary<string, string> { ["_Room"] = "room", ["_ResiFSI"] = "fsi_resi", ["_PropWork"] = "footprint" },
        [new FloorFrame("Typical floor plan", [1, 2, 3], [100_000, 0, 130_000, 30_000], [-95.0, 2.0])]);

    private static DrawingPolyline Rect(string handle, string layer, double x0, double y0, double x1, double y1) =>
        new(handle, layer, [new Pt(x0, y0), new Pt(x1, y0), new Pt(x1, y1), new Pt(x0, y1)]);

    [Fact]
    public void Rooms_are_moved_onto_the_plot_and_footprints_only_scaled()
    {
        var live = new DrawingLive(Frames, new Dictionary<string, string> { ["A1"] = "Living" });
        LiveSnapshot snap = live.Snapshot(
            [Rect("A1", "_ROOM", 101_000, 1_000, 105_000, 4_000), Rect("F1", "_PropWork", 5_000, 3_000, 15_000, 13_000),
             Rect("X1", "_Room", 0, 0, 1_000, 1_000)],  // a room outside every floor plan: ignored
            checkedUsedM2: null);

        Assert.Equal(2, snap.Outlines.Count);
        LiveOutline room = snap.Outlines.Single(o => o.ElementId == "A1");
        Assert.Equal("Living", room.Label);
        Assert.Equal(6.0, room.Points[0].X, 6);
        Assert.Equal(3.0, room.Points[0].Y, 6);
        Assert.Equal(new Pt(5, 3), snap.Outlines.Single(o => o.ElementId == "F1").Points[0]);
        Assert.Null(snap.BuiltUpM2);
    }

    [Fact]
    public void Fsi_moves_by_the_change_in_drawn_area_times_the_floors_a_plan_stands_for()
    {
        var live = new DrawingLive(Frames);
        DrawingPolyline before = Rect("B1", "_ResiFSI", 101_000, 1_000, 111_000, 11_000); // 100 m² × 3 floors
        live.SetBaseline([before]);
        Assert.Equal(1234.0, live.Snapshot([before], 1234.0).BuiltUpM2);

        DrawingPolyline wider = Rect("B1", "_ResiFSI", 101_000, 1_000, 113_000, 11_000); // +20 m² × 3
        Assert.Equal(1294.0, live.Snapshot([wider], 1234.0).BuiltUpM2);
    }

    [Fact]
    public void A_new_room_is_built_up_area_and_a_room_inside_the_fsi_outline_is_not_counted_twice()
    {
        var live = new DrawingLive(Frames);
        DrawingPolyline fsi = Rect("B1", "_ResiFSI", 101_000, 3_000, 111_000, 13_000); // 100 m² × 3 floors
        DrawingPolyline inside = Rect("R1", "_Room", 102_000, 4_000, 106_000, 8_000);
        live.SetBaseline([fsi, inside]);
        Assert.Equal(1234.0, live.Snapshot([fsi, inside], 1234.0).BuiltUpM2);

        // A 4 × 2 m room drawn out past the FSI outline: +8 m² on each of the 3 floors.
        DrawingPolyline bay = Rect("R2", "_Room", 103_000, 1_000, 107_000, 3_000);
        Assert.Equal(1258.0, live.Snapshot([fsi, inside, bay], 1234.0).BuiltUpM2);
        // The FSI outline then stretched over the same bay: no change, it isn't counted twice.
        DrawingPolyline grown = Rect("B1", "_ResiFSI", 101_000, 1_000, 111_000, 13_000);
        Assert.Equal(1294.0, live.Snapshot([grown, inside, bay], 1234.0).BuiltUpM2);
        Assert.Contains(live.Snapshot([grown], null).Outlines, o => o.ElementId == "B1" && o.Label == "built-up area");
    }

    [Fact]
    public void A_point_round_trips_between_drawing_and_plot()
    {
        var live = new DrawingLive(Frames);
        FloorFrame f = live.FloorOf(new Pt(120_000, 10_000))!;
        Pt back = live.ToDrawing(live.ToModel(new Pt(120_000, 10_000), f), f);
        Assert.Equal(120_000, back.X, 6);
        Assert.Equal(10_000, back.Y, 6);
        Assert.True(live.Watches("_resifsi"));
        Assert.False(live.Watches("_Furniture"));
    }
}
