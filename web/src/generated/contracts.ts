// GENERATED — DO NOT EDIT. Source: schemas/*.schema.json. Regenerate with `just codegen`.
/**
 * One building, normalised from Revit or IFC (ROADMAP §5.1). SI units. Any measured value
 * may be null; the engine then reports 'cannot verify'.
 */
export interface BuildingModel {
    /**
     * Free-text notes for hand-written fixtures (e.g. the list of deliberate failures). Ignored
     * by the engine.
     */
    _notes?:        string[];
    areas:          Area[];
    building:       Building;
    doors:          Door[];
    levels:         Level[];
    meta:           Meta;
    project:        Project;
    schema_version: SchemaVersion;
    site:           Site;
    spaces:         Space[];
    stairs:         Stair[];
    units:          Unit[];
}

/**
 * Revit Area (area plan) or equivalent, used for built-up / FSI.
 */
export interface Area {
    area_m2:       number | null;
    counts_to_far: FactBool;
    id:            string;
    level_id:      string;
    name:          string;
    scheme:        string;
    source_id:     null | string;
}

/**
 * Plot lies in a congested area as shown in the Development Plan / Gaothan (UDCPR 6.1 vs
 * 6.2 margins and FSI). Declared.
 */
export interface FactBool {
    confidence?: number | null;
    note?:       null | string;
    source:      Source;
    value:       boolean | null;
}

/**
 * Where a fact came from (D4). 'declared' always wins over the others.
 */
export type Source = "model" | "inferred" | "declared" | "default";

export interface Building {
    footprint: Array<number[]> | null;
    /**
     * Elevation of the highest point of any element.
     */
    highest_point_m: number | null;
    /**
     * Elevation of the highest roof/terrace finish.
     */
    roof_top_m: number | null;
}

export interface Door {
    from_space_id: null | string;
    height_m:      number | null;
    id:            string;
    is_exit:       FactBool;
    level_id:      string;
    source_id:     null | string;
    to_space_id:   null | string;
    width_m:       number | null;
}

export interface Level {
    elevation_m: number;
    id:          string;
    is_basement: boolean;
    name:        string;
    source_id:   null | string;
}

export interface Meta {
    exported_at:  Date;
    source_file:  null | string;
    source_kind:  SourceKind;
    tool_version: null | string;
}

export type SourceKind = "revit" | "ifc" | "manual";

export interface Project {
    /**
     * e.g. 'pmc'; matches rules/cities/<id>/.
     */
    authority_id:  FactString;
    building_type: FactBuildingType;
    /**
     * Plot lies in a congested area as shown in the Development Plan / Gaothan (UDCPR 6.1 vs
     * 6.2 margins and FSI). Declared.
     */
    congested_area: FactBool;
    location:       FactLatLon;
    name:           string;
    occupancy:      FactOccupancy;
    overlays:       Overlays;
    /**
     * Ordered, later overrides earlier, e.g. [nbc2016, udcpr2020, pmc] (D15).
     */
    rulesets: FactStringList;
    special:  Special;
    /**
     * Development Plan land-use zone, as declared.
     */
    zone: FactString;
}

/**
 * e.g. 'pmc'; matches rules/cities/<id>/.
 *
 * Development Plan land-use zone, as declared.
 */
export interface FactString {
    confidence?: number | null;
    note?:       null | string;
    source:      Source;
    value:       null | string;
}

export interface FactBuildingType {
    confidence?: number | null;
    note?:       null | string;
    source:      Source;
    value:       BuildingType | null;
}

export type BuildingType = "group_housing" | "standalone" | "bungalow_self_use" | "mixed_use" | "other";

export interface FactLatLon {
    confidence?: number | null;
    note?:       null | string;
    source:      Source;
    value:       LatLon | null;
}

export interface LatLon {
    lat: number;
    lon: number;
}

export interface FactOccupancy {
    confidence?: number | null;
    note?:       null | string;
    source:      Source;
    value:       Occupancy | null;
}

export interface Occupancy {
    group: OccupancyGroup;
    /**
     * e.g. 'A-4', as printed in the source.
     */
    subdivision: null | string;
}

export type OccupancyGroup = "A" | "B" | "C" | "D" | "E" | "F" | "G" | "H" | "J";

/**
 * Spatial overlays (D18, D22).
 */
export interface Overlays {
    metro_tod:             FactBool;
    nearest_metro_station: FactMetroStation;
    /**
     * 0..1; declared only in v1 (UDCPR 14.2.1.2.4).
     */
    plot_share_in_tod: FactNumber;
}

export interface FactMetroStation {
    confidence?: number | null;
    note?:       null | string;
    source:      Source;
    value:       MetroStation | null;
}

export interface MetroStation {
    distance_m: number;
    line:       null | string;
    name:       string;
    status:     LineStatus;
}

export type LineStatus = "operational" | "under_construction" | "proposed" | "unknown";

/**
 * 0..1; declared only in v1 (UDCPR 14.2.1.2.4).
 *
 * Plot area as per ownership documents.
 */
export interface FactNumber {
    confidence?: number | null;
    note?:       null | string;
    source:      Source;
    value:       number | null;
}

/**
 * Ordered, later overrides earlier, e.g. [nbc2016, udcpr2020, pmc] (D15).
 */
export interface FactStringList {
    confidence?: number | null;
    note?:       null | string;
    source:      Source;
    value:       string[] | null;
}

/**
 * Declared yes/no constraints (D19). metro_rail_within_20m triggers the Metro NOC advisory
 * (UDCPR 14.2.1.7).
 */
export interface Special {
    airport_zone:          FactBool;
    coastal:               FactBool;
    defence_vicinity:      FactBool;
    heritage:              FactBool;
    hill_slope_bdp:        FactBool;
    ht_line:               FactBool;
    metro_rail_within_20m: FactBool;
    railway:               FactBool;
    river_flood_line:      FactBool;
}

export type SchemaVersion = "1.0";

export interface Site {
    /**
     * From property lines. Null means site checks can't be verified.
     */
    boundary:       Array<number[]> | null;
    edges:          Edge[];
    ground_level_m: number | null;
    is_corner_plot: FactBool;
    /**
     * Plot area as per ownership documents.
     */
    plot_area_declared_m2: FactNumber;
}

/**
 * One side of the plot boundary. Road width is a legal fact: declared, never measured (D5).
 */
export interface Edge {
    a:                number[];
    b:                number[];
    id:               string;
    kind:             FactEdgeKind;
    road_width_basis: FactRoadWidthBasis;
    road_width_m:     FactNumber;
}

export interface FactEdgeKind {
    confidence?: number | null;
    note?:       null | string;
    source:      Source;
    value:       EdgeKind | null;
}

export type EdgeKind = "road" | "neighbour" | "open_space";

export interface FactRoadWidthBasis {
    confidence?: number | null;
    note?:       null | string;
    source:      Source;
    value:       RoadWidthBasis | null;
}

export type RoadWidthBasis = "existing" | "development_plan";

export interface Space {
    area_m2:        number | null;
    clear_height_m: number | null;
    id:             string;
    level_id:       string;
    name:           string;
    polygon:        Array<number[]> | null;
    source_id:      null | string;
    usage:          FactUsage;
}

export interface FactUsage {
    confidence?: number | null;
    note?:       null | string;
    source:      Source;
    value:       Usage | null;
}

export type Usage = "habitable" | "bedroom" | "living" | "kitchen" | "bathroom" | "wc" | "corridor" | "stair" | "lobby" | "parking" | "office" | "retail" | "assembly" | "storage" | "utility" | "other";

export interface Stair {
    base_level_id:   string;
    id:              string;
    is_exit:         FactBool;
    min_run_width_m: number | null;
    riser_m:         number | null;
    source_id:       null | string;
    top_level_id:    null | string;
    tread_m:         number | null;
}

/**
 * A tenement / flat (TOD 14.2.1.3).
 */
export interface Unit {
    carpet_area_m2: number | null;
    id:             string;
    level_id:       string;
    name:           string;
    source_id:      null | string;
    use:            FactUnitUse;
}

export interface FactUnitUse {
    confidence?: number | null;
    note?:       null | string;
    source:      Source;
    value:       UnitUse | null;
}

export type UnitUse = "residential" | "commercial" | "office" | "other";

/**
 * One compliance rule, stored as one YAML file under rules/<ruleset>/ (ROADMAP §5.2).
 * Expressions are Python-syntax strings evaluated only by engine/expr.py (AST whitelist,
 * never eval/exec).
 */
export interface Rule {
    /**
     * Optional; default True. False → not_applicable.
     */
    applies_when?: string;
    /**
     * Rule set this rule belongs to, e.g. nbc2016 | udcpr2020 | pmc.
     */
    authority: string;
    /**
     * Must evaluate to a bool. For advisory rules, True means the obligation is triggered.
     */
    check:  string;
    clause: Clause;
    /**
     * 'human' or 'agent:<model-id>@<prompt-version>'.
     */
    compiled_by: string;
    /**
     * Unit shown with fix_by, e.g. 'm', 'm2'. Null = no unit.
     */
    fix_unit?: null | string;
    /**
     * Evaluate once per element of this collection; the element is available as `item`.
     */
    for_each?:  Collection | null;
    freshness?: Freshness;
    /**
     * Note from a reference-only document (e.g. NBCS 2026). Never affects status (D20).
     */
    guidance_note?: GuidanceNote | null;
    /**
     * <authority>.<part>.<slug>, unique across all rule sets.
     */
    id: string;
    /**
     * 'check' produces pass/fail; 'advisory' produces an obligation the model can't confirm
     * (D23).
     */
    kind?: RuleKind;
    /**
     * Optional named expression, available to `check` as `limit`.
     */
    limit?: string;
    /**
     * Optional named expression, available to `check` as `measured`.
     */
    measured?: string;
    /**
     * str.format template; may use {measured} and {limit} with format specs.
     */
    message: string;
    /**
     * Tag used by the FSI headroom summary (P2.8).
     */
    metric?: Metric | null;
    /**
     * Rule id from an earlier rule set that this rule replaces for projects using both sets.
     */
    overrides?: null | string;
    /**
     * Notes from the reviewer model (P3.5 --review).
     */
    review_notes?: null | string;
    severity:      Severity;
    /**
     * Only a human sets 'verified'.
     */
    status: RuleStatus;
    title:  string;
}

/**
 * Citation copied from source text, never from memory (D13).
 */
export interface Clause {
    /**
     * Up to 2 sentences, verbatim.
     */
    excerpt: string;
    /**
     * Exactly as printed in the source, e.g. '14.2.1.2'.
     */
    ref:        string;
    retrieved?: Date | null;
    /**
     * Manifest doc id + printed page, e.g. 'udcpr2020 p.266'.
     */
    source: string;
}

export type Collection = "spaces" | "areas" | "stairs" | "doors" | "levels" | "units" | "site.edges";

export interface Freshness {
    checked: Date | null;
    status:  FreshnessStatus;
    url:     null | string;
}

export type FreshnessStatus = "unchecked" | "current" | "possibly_superseded";

export interface GuidanceNote {
    /**
     * Manifest doc id + page.
     */
    source: string;
    text:   string;
}

/**
 * 'check' produces pass/fail; 'advisory' produces an obligation the model can't confirm
 * (D23).
 */
export type RuleKind = "check" | "advisory";

export type Metric = "fsi_used" | "fsi_base" | "fsi_max";

export type Severity = "critical" | "major" | "minor";

/**
 * Only a human sets 'verified'.
 */
export type RuleStatus = "draft" | "verified";

/**
 * Lookup table used by rule expressions via table(name, *keys) (ROADMAP §5.2). Stored under
 * rules/<ruleset>/tables/<name>.yaml.
 * - map: table(name, key) → entries[key]
 * - bands: table(name, x) → value of the band with min <= x < max (max null = no upper
 * bound)
 * - map_of_bands: table(name, key, x) → bands of map[key], then as 'bands'
 */
export interface LookupTable {
    authority: string;
    /**
     * kind=bands.
     */
    bands?:       Band[];
    description?: null | string;
    kind:         Kind;
    /**
     * kind=map. Keys are strings; numeric keys are written as strings.
     */
    map?: { [key: string]: boolean | number | null | string };
    /**
     * kind=map_of_bands.
     */
    map_of_bands?: { [key: string]: Band[] };
    /**
     * Unique; referenced as table('<name>', ...).
     */
    name:   string;
    source: Clause;
    /**
     * Unit of the values, e.g. 'm', 'fsi'.
     */
    unit?: null | string;
}

export interface Band {
    /**
     * Exclusive; null = no upper bound.
     */
    max: number | null;
    /**
     * Inclusive.
     */
    min:   number;
    value: boolean | number | null | string;
}

export type Kind = "map" | "bands" | "map_of_bands";

/**
 * Result of one compliance check job (ROADMAP §5.4). Pass/fail comes only from
 * engine/evaluate.py; agents only add wording (explanation) and freshness.
 */
export interface CheckReport {
    created_at: Date;
    /**
     * Plain-language summary from the explainer agent (P3.8).
     */
    explanation: null | string;
    fsi:         FsiSummary | null;
    id:          string;
    /**
     * Id of the BuildingModel version that was checked.
     */
    model_version: string;
    project_id:    string;
    questions:     Question[];
    results:       Result[];
    /**
     * Hash of all rule and table files used.
     */
    ruleset_version: string;
    summary:         Summary;
}

/**
 * FSI used vs permitted, built only from rule-table limits (P2.8, D30). Numbers are null
 * when inputs are missing.
 */
export interface FsiSummary {
    base_permissible: number | null;
    basis:            string[];
    built_up_m2:      number | null;
    /**
     * Negative = over the limit.
     */
    headroom_base_m2: number | null;
    headroom_max_m2:  number | null;
    max_permissible:  number | null;
    missing_inputs:   string[];
    plot_area_m2:     number | null;
    rule_ids:         string[];
    used:             number | null;
}

/**
 * A missing input, ranked by how many checks it unlocks (P2.5).
 */
export interface Question {
    input_type: InputType;
    options:    string[] | null;
    path:       string;
    prompt:     string;
    rule_ids:   string[];
    unlocks:    number;
}

export type InputType = "number" | "enum" | "bool" | "latlon" | "edge_tags" | "text";

export interface Result {
    clause:         Clause;
    element:        ElementRef | null;
    facts_used:     FactUsed[];
    fix_by:         FixBy | null;
    freshness:      Freshness;
    guidance_note?: GuidanceNoteClass | null;
    limit:          boolean | number | null | string;
    measured:       boolean | number | null | string;
    message:        string;
    missing_inputs: string[];
    rule_id:        string;
    rule_status:    RuleStatus;
    severity:       Severity;
    status:         Status;
    title:          string;
}

/**
 * Points a result at one element. source_id is the Revit UniqueId or IFC GlobalId used to
 * send results back.
 */
export interface ElementRef {
    id:        string;
    kind:      ElementKind;
    source_id: null | string;
}

export type ElementKind = "spaces" | "areas" | "stairs" | "doors" | "levels" | "units" | "site.edges" | "site" | "building";

export interface FactUsed {
    /**
     * e.g. 'site.edges[e2].road_width_m'.
     */
    path:   string;
    source: Source;
    /**
     * The value that was read (any JSON).
     */
    value: any;
}

/**
 * How much the measured value must change to pass (D30). Only for comparison failures.
 */
export interface FixBy {
    amount:    number;
    direction: FixDirection;
    unit:      null | string;
}

export type FixDirection = "increase" | "decrease";

export interface GuidanceNoteClass {
    source: string;
    text:   string;
}

export type Status = "pass" | "fail" | "unverifiable" | "not_applicable" | "advisory";

export interface Summary {
    advisory:       number;
    fail:           number;
    not_applicable: number;
    pass:           number;
    unverifiable:   number;
}
