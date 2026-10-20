using System.Text.RegularExpressions;
using ComplianceChecker.Generated;

namespace ComplianceChecker.Core.Model;

/// <summary>
/// First-pass room use from the room name (deterministic keywords). Anything it can't place is left
/// unknown (null), so the Nemotron classifier (P3.7) or the user fills it — never a silent guess.
/// </summary>
public static class UsageGuess
{
    private static readonly (Regex Pattern, Usage Usage)[] Rules =
    {
        (Word("bed|bedroom|br|master"), Usage.Bedroom),
        (Word("living|hall|drawing|family|lounge"), Usage.Living),
        (Word("kitchen|kit|pantry"), Usage.Kitchen),
        (Word("wc|w\\.c\\.|water closet|powder"), Usage.Wc),
        (Word("toilet|bath|bathroom|washroom|wash"), Usage.Bathroom),
        (Word("corridor|passage|lobby corridor"), Usage.Corridor),
        (Word("stair|staircase|stairwell"), Usage.Stair),
        (Word("lobby|foyer|entrance"), Usage.Lobby),
        (Word("lift|elevator"), Usage.Utility), // after lobby: "Lift Lobby" is a lobby
        (Word("balcony|terrace|verandah|sit-out|deck"), Usage.Other),
        (Word("parking|garage|stilt"), Usage.Parking),
        (Word("office|cabin|workstation"), Usage.Office),
        (Word("shop|retail|store front|showroom"), Usage.Retail),
        (Word("store|storage|utility|services|electrical|shaft"), Usage.Storage),
        (Word("dining|study|room"), Usage.Habitable),
    };

    private static Regex Word(string alternatives) =>
        new($@"(^|[^a-z])({alternatives})([^a-z]|$)", RegexOptions.IgnoreCase | RegexOptions.CultureInvariant);

    public static FactUsage Guess(string roomName)
    {
        foreach (var (pattern, usage) in Rules)
            if (pattern.IsMatch(roomName))
                return new FactUsage { Value = usage, Source = Source.Inferred, Confidence = 0.7, Note = "from room name" };
        return new FactUsage { Value = null, Source = Source.Default, Note = $"use of '{roomName}' not recognised" };
    }
}
