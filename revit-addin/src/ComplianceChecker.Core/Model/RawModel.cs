namespace ComplianceChecker.Core.Model;

/// <summary>A 2D point in project coordinates, metres.</summary>
public readonly record struct Pt(double X, double Y);

/// <summary>
/// What the Revit exporter reads, already converted to SI units (metres, m², degrees) and with
/// every elevation measured from the same origin. No Revit types here, so it can be unit-tested;
/// <see cref="ModelBuilder"/> turns it into the BuildingModel contract.
/// </summary>
public sealed class RawModel
{
    public string ProjectName { get; set; } = "";
    public string? SourceFile { get; set; }
    public string ToolVersion { get; set; } = "";

    /// <summary>Revit's project location, if set. Often a template default, so it's marked for confirmation.</summary>
    public double? Latitude { get; set; }
    public double? Longitude { get; set; }

    /// <summary>Unordered property-line segments; chained into a boundary loop by the builder.</summary>
    public List<(Pt A, Pt B)> PropertyLineSegments { get; set; } = new();

    public List<Pt>? Footprint { get; set; }
    public double? GroundLevelM { get; set; }
    public double? RoofTopM { get; set; }
    public double? HighestPointM { get; set; }

    public List<RawLevel> Levels { get; set; } = new();
    public List<RawRoom> Rooms { get; set; } = new();
    public List<RawArea> Areas { get; set; } = new();
    public List<RawStair> Stairs { get; set; } = new();
    public List<RawDoor> Doors { get; set; } = new();

    /// <summary>Things the exporter couldn't read; shown to the user, not sent to the server.</summary>
    public List<string> Warnings { get; } = new();
}

public sealed record RawLevel(string Id, string? UniqueId, string Name, double ElevationM);

public sealed record RawRoom(
    string Id, string? UniqueId, string Name, string LevelId, double? AreaM2, double? ClearHeightM,
    List<Pt>? Polygon, string? HeightNote = null);

/// <summary>A Revit Area. Its scheme decides whether it is FSI built-up area or a tenement (unit).</summary>
public sealed record RawArea(string Id, string? UniqueId, string Scheme, string LevelId, string Name, double? AreaM2);

public sealed record RawStair(
    string Id, string? UniqueId, string BaseLevelId, string? TopLevelId,
    double? MinRunWidthM, double? RiserM, double? TreadM);

public sealed record RawDoor(
    string Id, string? UniqueId, string LevelId, double? WidthM, double? HeightM,
    string? FromRoomId, string? ToRoomId);
