"""Generate the two demo buildings as BuildingModel JSON.

Usage: just make-samples   (runs this, then turns every fixture into an IFC)

Unlike the small test fixtures, these are complete buildings: every floor is tiled with rooms, doors
connect the rooms (the IFC generator places them in the walls between `from_space_id` and
`to_space_id`), and the site carries everything the rules need, so a check asks no questions.

demo_apartment  G+11 mixed-use tower (36.4 m) near a metro station (TOD zone), 10.5 m DP road, on a
  50 × 51 m plot. Planted failures: over 36 m on a road under 12 m (PMC 10.1.1) · front margin
  2.5 m < 3.0 · east side margin 7.0 m < 7.28 (H/5) · FSI 2.60 > 2.5 (TOD) · mixed use needs a
  12 m road · stair 1.0 m < 1.2 m (building over 15 m) · entrance door 0.85 m
  < 0.90 m · Floor 1 built 2.8 m floor-to-floor, so every room is 2.6 m clear: habitable rooms
  < 2.75 and kitchens < 2.75 · Flat 105 studio carpet 24 sq.m < 25 sq.m (TOD).
demo_house      Two-storey bungalow on a 9 m road. Planted failures: east side margin 1.1 m < 1.5 m
  (Table 6-D) · entrance door 0.8 m < 0.9 m.
"""

from __future__ import annotations

import json
import sys

from compliance.adapters.usage import guess
from compliance.config import REPO_ROOT
from compliance.schemas import errors

OUT = REPO_ROOT / "fixtures" / "models"


def fact(value, source="declared", **extra):
    return {"value": value, "source": source, **extra}


def rect(x0, y0, x1, y1):
    return [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]


class Building:
    def __init__(self, name: str) -> None:
        self.name = name
        self.spaces: list[dict] = []
        self.doors: list[dict] = []
        self.units: list[dict] = []

    def room(self, sid, name, level, x0, y0, x1, y1, h):
        x0, x1 = sorted((round(x0, 3), round(x1, 3)))
        y0, y1 = sorted((round(y0, 3), round(y1, 3)))
        self.spaces.append({
            "id": sid, "source_id": f"demo-sp-{sid}", "name": name, "level_id": level,
            "usage": guess(name), "area_m2": round((x1 - x0) * (y1 - y0), 4),
            "clear_height_m": h, "polygon": rect(x0, y0, x1, y1),
        })  # fmt: skip
        return sid

    def door(self, level, a, b, w, h=2.1, exit_=False):
        did = f"D{len(self.doors) + 1:03d}"
        self.doors.append({
            "id": did, "source_id": f"demo-dr-{did}", "level_id": level,
            "width_m": w, "height_m": h,
            "is_exit": {"value": exit_, "source": "inferred", "confidence": 0.7,
                        "note": "Pset_DoorCommon.IsExternal"},
            "from_space_id": a, "to_space_id": b,
        })  # fmt: skip

    def unit(self, uid, name, level, carpet, use="residential"):
        self.units.append({
            "id": uid, "source_id": f"demo-un-{uid}", "name": name, "level_id": level,
            "carpet_area_m2": carpet, "use": {"value": use, "source": "model"},
        })  # fmt: skip


def model(b: Building, *, project: dict, site: dict, levels, footprint, roof, gfa, stair, notes):
    return {
        "schema_version": "1.0",
        "_notes": notes,
        "meta": {
            "source_kind": "manual",
            "source_file": f"{b.name}.json",
            "exported_at": "2026-10-20T10:00:00Z",
            "tool_version": "demo-1",
        },
        "project": project,
        "site": site,
        "levels": [
            {"id": lid, "source_id": f"demo-lvl-{lid}", "name": name, "elevation_m": z,
             "is_basement": False}
            for lid, name, z in levels
        ],  # fmt: skip
        "building": {"footprint": footprint, "roof_top_m": roof, "highest_point_m": roof},
        "spaces": b.spaces,
        "areas": [
            {"id": f"A{i}", "source_id": f"demo-ar-{i}", "scheme": "Gross Building",
             "level_id": lid, "name": f"BUA {name}", "area_m2": round(gfa[lid], 4),
             "counts_to_far": {"value": True, "source": "model"}}
            for i, (lid, name, _) in enumerate(levels)
        ],  # fmt: skip
        "stairs": stair if isinstance(stair, list) else [stair],
        "doors": b.doors,
        "units": b.units,
    }


def project_facts(name, lat, lon, occ, building_type, tod):
    no = fact(False)
    return {
        "name": name,
        "location": fact({"lat": lat, "lon": lon}),
        "authority_id": fact("pmc", "inferred"),
        "rulesets": fact(["nbc2016", "udcpr2020", "pmc"], "inferred"),
        "occupancy": fact({"group": "A", "subdivision": occ}),
        "zone": fact("residential"),
        "congested_area": fact(False),
        "special": {
            k: dict(no)
            for k in ("heritage", "coastal", "airport_zone", "ht_line", "railway",
                      "river_flood_line", "hill_slope_bdp", "defence_vicinity",
                      "metro_rail_within_20m")
        },  # fmt: skip
        "building_type": fact(building_type),
        "overlays": {
            "nearest_metro_station": fact(None, "default"),
            "metro_tod": fact(tod),
            "plot_share_in_tod": fact(1.0 if tod else 0.0),
        },
    }


def site_facts(w, d, road_width, plot_area):
    corners = rect(0, 0, w, d)
    edges = []
    for i in range(4):
        road = i == 0
        edges.append({
            "id": f"e{i + 1}", "a": corners[i], "b": corners[(i + 1) % 4],
            "kind": fact("road" if road else "neighbour"),
            "road_width_m": fact(road_width) if road else fact(None, "default"),
            "road_width_basis": fact("development_plan") if road else fact(None, "default"),
        })  # fmt: skip
    return {
        "boundary": corners,
        "plot_area_declared_m2": fact(plot_area),
        "is_corner_plot": fact(False),
        "ground_level_m": 0.0,
        "edges": edges,
    }


# ---------------------------------------------------------------------------- apartment

W0, W1, C0, C1, E0, E1 = 24.3, 32.8, 32.8, 34.5, 34.5, 43.0  # west flats · corridor · east flats
ROWS = {"front": (2.5, 11.5), "core": (11.5, 16.5), "rear_a": (16.5, 25.0), "rear_b": (25.0, 33.5)}


def flat_xy(side, row):
    """Map a flat template's (u, v) to plan (x, y). u = 0 at the outer wall, 8.5 at the corridor."""
    y0 = ROWS[row][0]
    if side == "W":
        return lambda u, v: (W0 + u, y0 + v)
    return lambda u, v: (E1 - u, y0 + v)


def place(b, level, side, row, sid, name, u0, v0, u1, v1, h):
    f = flat_xy(side, row)
    (x0, y0), (x1, y1) = f(u0, v0), f(u1, v1)
    return b.room(sid, name, level, x0, y0, x1, y1, h)


def two_bhk(b, level, side, flat, corridor):
    """Front row (8.5 × 9, the front and one side on the façade): every habitable room and the
    kitchen get a window; bath and WC sit on a ventilation shaft."""
    p = f"{flat}-"
    n = f"Flat {flat}"
    bed2 = place(b, level, side, "front", p + "BR2", f"{n} Bedroom 2", 0, 0, 3.5, 4.5, 2.8)
    kitchen = place(b, level, side, "front", p + "KIT", f"{n} Kitchen", 3.5, 0, 6.0, 4.5, 2.8)
    bed1 = place(b, level, side, "front", p + "BR1", f"{n} Bedroom 1", 6.0, 0, 8.5, 4.5, 2.8)
    living = place(b, level, side, "front", p + "LIV", f"{n} Living", 0, 4.5, 3.5, 9, 2.8)
    passage = place(b, level, side, "front", p + "PAS", f"{n} Passage", 3.5, 4.5, 8.5, 6.0, 2.8)
    bath = place(b, level, side, "front", p + "BTH", f"{n} Bath", 3.5, 6.0, 5.5, 9, 2.4)
    place(b, level, side, "front", p + "SFT", f"{n} Shaft", 5.5, 6.0, 6.3, 9, 2.4)
    wc = place(b, level, side, "front", p + "WC", f"{n} WC", 6.3, 6.0, 7.6, 9, 2.4)
    store = place(b, level, side, "front", p + "STO", f"{n} Store", 7.6, 6.0, 8.5, 9, 2.4)
    b.door(level, passage, corridor, 1.0)
    b.door(level, living, passage, 0.9)
    b.door(level, bed2, living, 0.9)
    b.door(level, kitchen, passage, 0.9)
    b.door(level, bed1, passage, 0.9)
    b.door(level, bath, passage, 0.75)
    b.door(level, wc, passage, 0.75)
    b.door(level, store, passage, 0.6)
    b.unit(flat, n, level, 66.0)


def one_bhk(b, level, side, row, flat, corridor):
    """Rear rows (8.5 × 8.5, one side on the façade): living, kitchen and bedroom along it; the
    bedroom's own bath on a shaft."""
    p = f"{flat}-"
    n = f"Flat {flat}"
    living = place(b, level, side, row, p + "LIV", f"{n} Living", 0, 0, 8.5, 3.5, 2.8)
    kitchen = place(b, level, side, row, p + "KIT", f"{n} Kitchen", 0, 3.5, 3.5, 5.5, 2.8)
    passage = place(b, level, side, row, p + "PAS", f"{n} Passage", 3.5, 3.5, 8.5, 5.5, 2.8)
    bed = place(b, level, side, row, p + "BR", f"{n} Bedroom", 0, 5.5, 4.5, 8.5, 2.8)
    bath = place(b, level, side, row, p + "BTH", f"{n} Bath", 4.5, 5.5, 6.5, 8.5, 2.4)
    place(b, level, side, row, p + "SFT", f"{n} Shaft", 6.5, 5.5, 7.3, 8.5, 2.4)
    store = place(b, level, side, row, p + "STO", f"{n} Store", 7.3, 5.5, 8.5, 8.5, 2.4)
    b.door(level, passage, corridor, 1.0)
    b.door(level, living, passage, 1.2)  # archway
    b.door(level, kitchen, passage, 0.9)
    b.door(level, bed, passage, 0.9)
    b.door(level, bath, bed, 0.75)
    b.door(level, store, passage, 0.6)
    b.unit(flat, n, level, 59.0)


def studio(b, level, side, row, flat, corridor):
    """Floor 1's small flat (24 sq.m carpet: under the TOD minimum, planted) beside the society
    store, which opens off the corridor."""
    p = f"{flat}-"
    n = f"Flat {flat}"
    living = place(b, level, side, row, p + "LIV", f"{n} Living", 0, 0, 4.5, 4.0, 2.8)
    kitchen = place(b, level, side, row, p + "KIT", f"{n} Kitchen", 0, 4.0, 2.5, 5.5, 2.8)
    bath = place(b, level, side, row, p + "BTH", f"{n} Bath", 4.5, 0, 6.0, 2.0, 2.4)
    place(b, level, side, row, p + "SFT", f"{n} Shaft", 6.0, 0, 6.8, 2.0, 2.4)
    store = place(b, level, side, row, p + "STO", f"{n} Store", 6.8, 0, 8.5, 2.0, 2.4)
    passage = place(b, level, side, row, p + "PAS", f"{n} Passage", 4.5, 2.0, 8.5, 4.0, 2.8)
    society = place(b, level, side, row, p + "SOC", f"Society Store {level}", 2.5, 4.0, 8.5, 8.5, 2.8)
    meters = place(b, level, side, row, p + "MTR", f"Meter Room {level}", 0, 5.5, 2.5, 8.5, 2.8)
    b.door(level, passage, corridor, 1.0)
    b.door(level, living, passage, 0.9)
    b.door(level, kitchen, living, 0.9)
    b.door(level, bath, passage, 0.75)
    b.door(level, store, passage, 0.6)
    b.door(level, society, corridor, 1.0)
    b.door(level, meters, society, 0.9)
    b.unit(flat, f"{n} (studio)", level, 24.0)


# The core across the building: Stair 1 (the planted 1.0 m flights), two lifts on their own lobby,
# the main lobby between the corridors, Stair 2 (1.5 m flights) and the electrical room.
STAIR2 = (37.2, 43.0, 13.3, 16.5)


def core(b, level, h):
    c0, c1 = ROWS["core"]
    stair = b.room(f"{level}-STR", f"Staircase {level}", level, W0, c0, W0 + 2.5, c1, h)
    lift1 = b.room(f"{level}-LF1", f"Lift 1 {level}", level, 26.8, c0, 29.0, 14.0, h)
    lift2 = b.room(f"{level}-LF2", f"Lift 2 {level}", level, 29.0, c0, 31.2, 14.0, h)
    llob = b.room(f"{level}-LLB", f"Lift Lobby {level}", level, 26.8, 14.0, 31.2, c1, h)
    lobby = b.room(f"{level}-LOB", f"Lobby {level}", level, 31.2, c0, 37.2, c1, h)
    x0, x1, y0, y1 = STAIR2
    stair2 = b.room(f"{level}-ST2", f"Staircase 2 {level}", level, x0, y0, x1, y1, h)
    elec = b.room(f"{level}-ELE", f"Electrical Room {level}", level, 37.2, c0, E1, y0, h)
    b.door(level, llob, stair, 1.0)
    b.door(level, lift1, llob, 1.0)
    b.door(level, lift2, llob, 1.0)
    b.door(level, llob, lobby, 1.5)  # archway
    b.door(level, stair2, lobby, 1.2)
    b.door(level, elec, lobby, 0.9)
    return lobby


UPPER = 11  # floors above the ground floor (G+11)
LOW_FLOOR = 2.8  # Floor 1 floor-to-floor (typical 3.0): with a 0.2 m slab, every room is 2.6 m clear


def apartment() -> dict:
    b = Building("demo_apartment")
    # Ground 3.6 m, Floor 1 squeezed to 2.8 m, then 3.0 m storeys.
    elevation = {0: 0.0, 1: 3.6, **{i: 3.6 + LOW_FLOOR + 3.0 * (i - 2) for i in range(2, UPPER + 1)}}
    levels = [("L0", "Ground Floor", 0.0)] + [(f"L{i}", f"Floor {i}", elevation[i]) for i in range(1, UPPER + 1)]
    roof = elevation[UPPER] + 3.0  # 36.4 m: over 36 m on a 10.5 m road (PMC 10.1.1 needs 12 m)
    f0, f1 = ROWS["front"]

    # Ground: two shops on the road, the residential entrance between them, stilt parking behind.
    shop1 = b.room("G-SH1", "Shop 1", "L0", W0, f0, 31.3, f1, 3.3)
    entrance = b.room("G-ENT", "Entrance Lobby", "L0", 31.3, f0, 36.0, f1, 3.3)
    shop2 = b.room("G-SH2", "Shop 2", "L0", 36.0, f0, E1, f1, 3.3)
    lobby = core(b, "L0", 3.3)
    parking = b.room("G-PRK", "Parking", "L0", W0, ROWS["rear_a"][0], E1, ROWS["rear_b"][1], 3.3)
    b.door("L0", shop1, None, 2.4, 2.4, exit_=True)
    b.door("L0", shop2, None, 2.4, 2.4, exit_=True)
    b.door("L0", entrance, None, 0.85, 2.1, exit_=True)  # too narrow for an exit
    b.door("L0", entrance, lobby, 2.0)  # archway into the core
    b.door("L0", lobby, parking, 1.2)
    b.unit("SH1", "Shop 1", "L0", 60.0, "commercial")
    b.unit("SH2", "Shop 2", "L0", 60.0, "commercial")

    for i in range(1, UPPER + 1):
        lv = f"L{i}"
        front = b.room(f"{lv}-COR", f"Corridor {lv}", lv, C0, f0, C1, f1, 2.8)
        lobby = core(b, lv, 2.8)
        rear = b.room(f"{lv}-CR2", f"Rear Corridor {lv}", lv, C0, ROWS["rear_a"][0], C1,
                      ROWS["rear_b"][1], 2.8)  # fmt: skip
        b.door(lv, front, lobby, 1.2)
        b.door(lv, lobby, rear, 1.2)
        two_bhk(b, lv, "W", f"{i}01", front)
        two_bhk(b, lv, "E", f"{i}02", front)
        one_bhk(b, lv, "W", "rear_a", f"{i}03", rear)
        one_bhk(b, lv, "E", "rear_a", f"{i}04", rear)
        (studio if i == 1 else one_bhk)(b, lv, "W", "rear_b", f"{i}05", rear)
        one_bhk(b, lv, "E", "rear_b", f"{i}06", rear)
    # The squeezed storey: every room on Floor 1 loses 0.2 m (wet rooms with a dropped ceiling keep 2.4 m).
    for sp in b.spaces:
        if sp["level_id"] == "L1":
            sp["clear_height_m"] = min(sp["clear_height_m"], LOW_FLOOR - 0.2)

    width = E1 - W0
    upper = width * (ROWS["rear_b"][1] - f0)
    gfa = {"L0": width * (ROWS["core"][1] - f0), **{f"L{i}": upper for i in range(1, UPPER + 1)}}
    stairs = [
        {
            "id": "ST1", "source_id": "demo-st-1", "base_level_id": "L0", "top_level_id": f"L{UPPER}",
            "min_run_width_m": 1.0, "riser_m": 0.1875, "tread_m": 0.25,
            "is_exit": {"value": True, "source": "model", "note": "Pset_StairCommon.FireExit"},
        },
        {
            "id": "ST2", "source_id": "demo-st-2", "base_level_id": "L0", "top_level_id": f"L{UPPER}",
            "min_run_width_m": 1.5, "riser_m": 0.1875, "tread_m": 0.25,
            "is_exit": {"value": True, "source": "model", "note": "Pset_StairCommon.FireExit"},
        },
    ]  # fmt: skip
    return model(
        b,
        project=project_facts("Demo — mixed-use building near a metro station", 18.556546,
                              73.909447, "A-4", "mixed_use", True),  # fmt: skip
        site=site_facts(50, 51, 10.5, 2550.0),
        levels=levels,
        footprint=rect(W0, f0, E1, ROWS["rear_b"][1]),
        roof=roof,
        gfa=gfa,
        stair=stairs,
        notes=[__doc__.split("demo_apartment", 1)[1].split("demo_house", 1)[0].strip()],
    )


# ---------------------------------------------------------------------------- house


def house() -> dict:
    b = Building("demo_house")
    dx = 1.4  # the house sits 1.4 m east of centre: east margin 1.1 m < 1.5 m (planted failure)

    def room(rid, name, lv, x0, y0, x1, y1, h):
        return b.room(rid, name, lv, x0 + dx, y0, x1 + dx, y1, h)

    levels = [("L0", "Ground Floor", 0.0), ("L1", "First Floor", 3.3)]
    # A door belongs to (and swings into) the room named first. Openings 1.2 m and wider between
    # living spaces are drawn as archways, without a leaf (dxf_detail). Nothing opens off the stair
    # except through the living room below and the lounge above.
    g = "L0"
    living = room("G-LIV", "Living", g, 2.5, 4, 8.7, 9.5, 3.0)
    dining = room("G-DIN", "Dining", g, 8.7, 4, 12.5, 9.5, 3.0)
    guest = room("G-BR", "Guest Bedroom", g, 2.5, 9.5, 6.5, 14, 3.0)
    gbath = room("G-BTH", "Guest Bath", g, 2.5, 14, 4.5, 16, 2.7)
    gstore = room("G-STO", "Store", g, 4.5, 14, 6.5, 16, 2.7)
    stair = room("G-STR", "Staircase", g, 6.5, 9.5, 8.7, 16, 3.0)
    kitchen = room("G-KIT", "Kitchen", g, 8.7, 9.5, 12.5, 13, 3.0)
    pantry = room("G-PAN", "Store", g, 8.7, 13, 10.6, 16, 2.7)
    utility = room("G-UTL", "Utility", g, 10.6, 13, 12.5, 16, 2.7)
    b.door(g, living, None, 0.8, 2.1, exit_=True)  # 0.8 m < 0.9 m exit door (planted)
    b.door(g, living, dining, 1.5)  # archway
    b.door(g, living, stair, 1.2)  # archway: the stair rises from the living room
    b.door(g, guest, living, 0.9)
    b.door(g, gbath, guest, 0.75)
    b.door(g, gstore, guest, 0.75)
    b.door(g, kitchen, dining, 0.9)
    b.door(g, pantry, kitchen, 0.75)
    b.door(g, utility, kitchen, 0.75)
    b.door(g, utility, None, 0.9, 2.1, exit_=True)  # back door

    f = "L1"
    master = room("F-MBR", "Master Bedroom", f, 4.5, 4, 8.7, 9.5, 3.0)
    bath1 = room("F-BT1", "Bath 1", f, 2.5, 4, 4.5, 7, 2.7)
    mstore = room("F-MST", "Store", f, 2.5, 7, 4.5, 9.5, 2.7)
    bed2 = room("F-BR2", "Bedroom 2", f, 8.7, 4, 12.5, 9.5, 3.0)
    bed3 = room("F-BR3", "Bedroom 3", f, 2.5, 9.5, 6.5, 14, 3.0)
    bath3 = room("F-BT3", "Bath 3", f, 2.5, 14, 6.5, 16, 2.7)
    landing = room("F-STR", "Staircase", f, 6.5, 9.5, 8.7, 16, 3.0)
    lounge = room("F-LNG", "Family Lounge", f, 8.7, 9.5, 12.5, 13, 3.0)
    bath2 = room("F-BT2", "Bath 2", f, 8.7, 13, 10.6, 16, 2.7)
    fstore = room("F-STO", "Store", f, 10.6, 13, 12.5, 16, 2.7)
    b.door(f, lounge, landing, 1.2)  # archway: the stair arrives in the lounge
    b.door(f, master, landing, 0.9)
    b.door(f, bath1, master, 0.75)
    b.door(f, mstore, master, 0.75)
    b.door(f, bed3, landing, 0.9)
    b.door(f, bath3, bed3, 0.75)
    b.door(f, bed2, lounge, 0.9)
    b.door(f, bath2, lounge, 0.75)
    b.door(f, fstore, lounge, 0.75)
    b.unit("H1", "House", g, 200.0)

    stair_ = {
        "id": "ST1", "source_id": "demo-st-1", "base_level_id": "L0", "top_level_id": "L1",
        "min_run_width_m": 1.0, "riser_m": 0.165, "tread_m": 0.28,
        "is_exit": {"value": False, "source": "model", "note": "Pset_StairCommon.FireExit"},
    }  # fmt: skip
    return model(
        b,
        project=project_facts("Demo — two-storey bungalow", 18.4655, 73.896, "A-2",
                              "bungalow_self_use", False),  # fmt: skip
        site=site_facts(15, 20, 9.0, 300.0),
        levels=levels,
        footprint=rect(2.5 + dx, 4, 12.5 + dx, 16),
        roof=6.6,
        gfa={"L0": 120.0, "L1": 120.0},
        stair=stair_,
        notes=[__doc__.split("demo_house", 1)[1].strip()],
    )


def main() -> int:
    for name, build in (("demo_apartment", apartment), ("demo_house", house)):
        m = build()
        errs = errors("building-model.schema.json", m)
        if errs:
            print(f"{name}: invalid model:", *errs[:5], sep="\n  ")
            return 1
        path = OUT / f"{name}.json"
        path.write_text(json.dumps(m, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"wrote {path.relative_to(REPO_ROOT).as_posix()} "
              f"({len(m['spaces'])} rooms, {len(m['doors'])} doors, {len(m['units'])} units)")  # fmt: skip
    return 0


if __name__ == "__main__":
    sys.exit(main())
