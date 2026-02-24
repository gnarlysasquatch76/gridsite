export var MAPBOX_TOKEN = process.env.NEXT_PUBLIC_MAPBOX_TOKEN || "";

export var US_STATES = [
  "AL","AK","AZ","AR","CA","CO","CT","DE","FL","GA",
  "HI","ID","IL","IN","IA","KS","KY","LA","ME","MD",
  "MA","MI","MN","MS","MO","MT","NE","NV","NH","NJ",
  "NM","NY","NC","ND","OH","OK","OR","PA","RI","SC",
  "SD","TN","TX","UT","VT","VA","WA","WV","WI","WY",
];

export var POWER_PLANTS_SOURCE = "power-plants";
export var POWER_PLANTS_LAYER = "power-plants-circles";
export var SUBSTATIONS_SOURCE = "substations";
export var SUBSTATIONS_LAYER = "substations-diamonds";
export var TRANSMISSION_LINES_SOURCE = "transmission-lines";
export var TRANSMISSION_LINES_LAYER = "transmission-lines-lines";
export var QUEUE_WITHDRAWALS_SOURCE = "queue-withdrawals";
export var QUEUE_WITHDRAWALS_LAYER = "queue-withdrawals-triangles";
export var SCORED_SITES_SOURCE = "scored-sites";
export var SCORED_SITES_LAYER = "scored-sites-stars";
export var RADIUS_CIRCLE_SOURCE = "radius-circle";
export var RADIUS_CIRCLE_FILL_LAYER = "radius-circle-fill";
export var RADIUS_CIRCLE_OUTLINE_LAYER = "radius-circle-outline";
export var FLOOD_ZONES_SOURCE = "flood-zones";
export var FLOOD_ZONES_LAYER = "flood-zones-raster";
export var BROADBAND_SOURCE = "broadband";
export var BROADBAND_LAYER = "broadband-raster";
export var BROWNFIELDS_SOURCE = "brownfields";
export var BROWNFIELDS_LAYER = "brownfields-circles";
export var DATA_CENTERS_SOURCE = "data-centers";
export var DATA_CENTERS_LAYER = "data-centers-squares";
export var UTILITY_TERRITORIES_SOURCE = "utility-territories";
export var UTILITY_TERRITORIES_LAYER = "utility-territories-fill";
export var UTILITY_TERRITORIES_OUTLINE_LAYER = "utility-territories-outline";
export var DIAMOND_ICON = "diamond-icon";
export var STAR_ICON = "star-icon";
export var TRIANGLE_ICON = "triangle-icon";
export var SQUARE_ICON = "square-icon";

export interface ScoredSite {
  plant_name: string;
  state: string;
  latitude: number;
  longitude: number;
  total_capacity_mw: number;
  fuel_type: string;
  status: string;
  planned_retirement_date?: string;
  composite_score: number;
  power_access: number;
  grid_capacity: number;
  site_characteristics: number;
  connectivity: number;
  risk_factors: number;
  nearest_sub_name: string;
  nearest_sub_distance_miles: number;
  nearest_sub_voltage_kv: number;
}

export interface ProximityResult {
  site: ScoredSite;
  radiusMiles: number;
  substations: {
    total: number;
    by500Plus: number;
    by345to499: number;
    by230to344: number;
    byUnder230: number;
  };
  transmissionLines: {
    total: number;
    by500Plus: number;
    by345to499: number;
    by230to344: number;
    byUnder230: number;
  };
  queueWithdrawals: {
    total: number;
    totalWithdrawnMW: number;
  };
}

export type LayerState = {
  powerPlants: boolean;
  substations: boolean;
  transmissionLines: boolean;
  queueWithdrawals: boolean;
  floodZones: boolean;
  broadband: boolean;
  brownfields: boolean;
  dataCenters: boolean;
  utilityTerritories: boolean;
};

export type LayerGroupState = {
  infrastructure: boolean;
  capacity: boolean;
  risk: boolean;
  connectivity: boolean;
};

export var LAYER_GROUPS = {
  infrastructure: ["powerPlants", "substations", "transmissionLines", "dataCenters"] as const,
  capacity: ["utilityTerritories", "queueWithdrawals"] as const,
  risk: ["floodZones", "brownfields"] as const,
  connectivity: ["broadband"] as const,
};

export var FLOOD_RISK_STATES = new Set(["LA", "FL", "TX", "MS", "AL", "SC", "NC"]);
export var MODERATE_FLOOD_STATES = new Set(["NJ", "DE", "MD", "VA", "GA", "CT", "RI", "MA", "HI"]);
export var BROADBAND_COVERAGE: Record<string, number> = {
  "NJ": 97, "CT": 96, "MA": 96, "RI": 95, "MD": 95, "DE": 94,
  "NY": 93, "VA": 93, "NH": 92, "PA": 91, "FL": 91, "IL": 90,
  "OH": 90, "CA": 90, "WA": 90, "CO": 89, "GA": 89, "TX": 89,
  "MI": 88, "NC": 88, "MN": 88, "OR": 87, "WI": 87, "IN": 86,
  "AZ": 86, "SC": 86, "TN": 85, "UT": 85, "NV": 85, "MO": 84,
  "KY": 83, "IA": 83, "AL": 82, "KS": 82, "NE": 81, "LA": 81,
  "OK": 80, "ID": 79, "SD": 78, "ND": 77, "WV": 76, "AR": 76,
  "NM": 75, "ME": 75, "VT": 74, "MT": 73, "WY": 72, "MS": 72,
  "AK": 70, "HI": 80,
};
