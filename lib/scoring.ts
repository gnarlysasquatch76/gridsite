import {
  ScoredSite,
  FLOOD_RISK_STATES,
  MODERATE_FLOOD_STATES,
  BROADBAND_COVERAGE,
} from "./constants";

export interface TtpEstimate {
  tier: "green" | "yellow" | "red";
  label: string;
  months: string;
}

/**
 * Estimate time-to-power based on scoring inputs.
 *
 * Green  (<12 mo): Retired plant with existing interconnection + capacity signals
 * Yellow (12-18 mo): Nearby infrastructure with capacity signals
 * Red    (>18 mo): New interconnection required or constrained area
 */
export function estimateTimeToPower(site: ScoredSite): TtpEstimate {
  var isPowerPlant = site.status === "retired" || site.status === "retiring";
  var closeSub = site.sub_distance_score >= 80;        // within ~10 mi
  var hasLines = site.tx_lines_score >= 25;             // at least 2 connected lines
  var hasCapacity = site.queue_withdrawal_score > 30;   // capacity signals present
  var farFromSub = site.sub_distance_score < 50;        // >25 mi from 345kV+ sub
  var noInfra = site.tx_lines_score < 25 && site.queue_withdrawal_score <= 30;

  // Green: retired plant with existing interconnection in surplus territory
  if (isPowerPlant && closeSub && hasLines && hasCapacity) {
    return { tier: "green", label: "< 12 mo", months: "Under 12 months" };
  }

  // Red: new interconnection required or constrained
  if (farFromSub || noInfra) {
    return { tier: "red", label: "> 18 mo", months: "Over 18 months" };
  }

  // Yellow: nearby infrastructure with capacity signals
  return { tier: "yellow", label: "12-18 mo", months: "12 to 18 months" };
}

export function haversineDistanceMiles(lat1: number, lon1: number, lat2: number, lon2: number): number {
  var R = 3958.8; // Earth radius in miles
  var dLat = (lat2 - lat1) * Math.PI / 180;
  var dLon = (lon2 - lon1) * Math.PI / 180;
  var a = Math.sin(dLat / 2) * Math.sin(dLat / 2) +
    Math.cos(lat1 * Math.PI / 180) * Math.cos(lat2 * Math.PI / 180) *
    Math.sin(dLon / 2) * Math.sin(dLon / 2);
  var c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
  return R * c;
}

export function isCoastalLocation(lat: number, lon: number, state: string): boolean {
  if (FLOOD_RISK_STATES.has(state)) {
    if (state === "FL") return true;
    if (state === "LA") return lat < 31.0 || lon < -91.0;
    if (state === "TX") return lon > -97.0 && lat < 30.5;
    if (state === "MS") return lat < 31.5;
    if (state === "AL") return lat < 31.5;
    if (state === "NC" || state === "SC") return lon > -80.0;
    return true;
  }
  return false;
}

export function computeLocationScore(
  lng: number,
  lat: number,
  substationsData: GeoJSON.FeatureCollection,
  queueWithdrawalsData: GeoJSON.FeatureCollection,
): ScoredSite | null {
  // Find nearest 345kV+ substation
  var bestDist = Infinity;
  var bestSub: { name: string; maxVolt: number; lines: number; state: string } | null = null;
  var subFeatures = substationsData.features;
  for (var i = 0; i < subFeatures.length; i++) {
    var sf = subFeatures[i];
    var maxVolt = sf.properties?.MAX_VOLT != null ? Number(sf.properties.MAX_VOLT) : 0;
    if (maxVolt < 345) continue;
    if (sf.geometry.type !== "Point") continue;
    var sCoords = (sf.geometry as GeoJSON.Point).coordinates;
    var dist = haversineDistanceMiles(lat, lng, sCoords[1], sCoords[0]);
    if (dist < bestDist) {
      bestDist = dist;
      bestSub = {
        name: sf.properties?.NAME || "",
        maxVolt: maxVolt,
        lines: sf.properties?.LINES != null ? Number(sf.properties.LINES) : 0,
        state: sf.properties?.STATE || "",
      };
    }
  }

  if (!bestSub) return null;

  // Count queue withdrawals within 20 miles
  var degDelta = 20 / 69.0;
  var lonDelta = degDelta / Math.max(Math.cos(lat * Math.PI / 180), 0.01);
  var qwCount = 0;
  var qwTotalMW = 0;
  var qwFeatures = queueWithdrawalsData.features;
  for (var qi = 0; qi < qwFeatures.length; qi++) {
    var qf = qwFeatures[qi];
    if (qf.geometry.type !== "Point") continue;
    var qCoords = (qf.geometry as GeoJSON.Point).coordinates;
    if (Math.abs(qCoords[1] - lat) > degDelta) continue;
    if (Math.abs(qCoords[0] - lng) > lonDelta) continue;
    var qDist = haversineDistanceMiles(lat, lng, qCoords[1], qCoords[0]);
    if (qDist <= 20) {
      qwCount++;
      qwTotalMW += qf.properties?.total_mw != null ? Number(qf.properties.total_mw) : 0;
    }
  }

  var state = bestSub.state;

  // --- Time to Power (50%) — distance + voltage + lines + queue withdrawals ---
  var distScore = Math.max(0, Math.min(100, 100 - bestDist * 2));
  var voltScore = 60;
  if (bestSub.maxVolt >= 765) voltScore = 100;
  else if (bestSub.maxVolt >= 500) voltScore = 85;
  else if (bestSub.maxVolt >= 345) voltScore = 70;
  var genCapScore = 0; // custom locations have no existing capacity
  var linesScore = Math.max(0, Math.min(100, bestSub.lines / 8 * 100));
  var qwScore: number;
  if (qwCount === 0) {
    qwScore = 30;
  } else {
    var countScore = Math.max(30, Math.min(100, 30 + qwCount * 5));
    var mwBonus = Math.max(0, Math.min(20, qwTotalMW / 5000 * 20));
    qwScore = Math.max(0, Math.min(100, countScore + mwBonus));
  }
  // Custom/brownfield: no gen capacity, distribute among distance/voltage/lines/queue
  var timeToPower = distScore * 0.35 + voltScore * 0.20 + linesScore * 0.20 + qwScore * 0.25;

  // --- Site Readiness (20%) — unknown site, base 65 ---
  var fuelTypeScore = 0;
  var capacityScaleScore = 0;
  var siteReadiness = 65;

  // --- Connectivity (15%) — longitude proxy + latitude band + broadband ---
  var lonScore = lng < -70 ? Math.max(0, Math.min(100, 100 - (lng + 70) * -1.2)) : 100;
  lonScore = Math.max(0, Math.min(100, lonScore));
  var latScore: number;
  if (lat >= 33 && lat <= 43) latScore = 90;
  else if (lat >= 28 && lat <= 48) latScore = 70;
  else latScore = 40;
  var bbPct = BROADBAND_COVERAGE[state] || 80;
  var bbScore: number;
  if (bbPct >= 95) bbScore = 95;
  else if (bbPct >= 90) bbScore = 85;
  else if (bbPct >= 85) bbScore = 75;
  else if (bbPct >= 80) bbScore = 65;
  else if (bbPct >= 75) bbScore = 50;
  else bbScore = 35;
  var connectivity = lonScore * 0.40 + latScore * 0.30 + bbScore * 0.30;

  // --- Risk Factors (15%) — unknown contamination + flood risk ---
  var floodScore: number;
  if (isCoastalLocation(lat, lng, state)) floodScore = 35;
  else if (MODERATE_FLOOD_STATES.has(state)) floodScore = 65;
  else floodScore = 90;
  var contamScore = 70;
  var statusScore = 0; // custom locations have no operational status
  var riskFactors = contamScore * 0.65 + floodScore * 0.35;

  // Composite
  var composite = timeToPower * 0.50 + siteReadiness * 0.20 + connectivity * 0.15 + riskFactors * 0.15;
  composite = Math.round(Math.max(0, Math.min(100, composite)) * 10) / 10;

  var r = function (v: number) { return Math.round(v * 10) / 10; };
  return {
    plant_name: "Custom Location",
    state: state,
    latitude: lat,
    longitude: lng,
    total_capacity_mw: 0,
    fuel_type: "Custom",
    status: "custom",
    composite_score: composite,
    time_to_power: r(timeToPower),
    site_readiness: r(siteReadiness),
    connectivity: r(connectivity),
    risk_factors: r(riskFactors),
    sub_distance_score: r(distScore),
    sub_voltage_score: r(voltScore),
    gen_capacity_score: r(genCapScore),
    tx_lines_score: r(linesScore),
    queue_withdrawal_score: r(qwScore),
    fuel_type_score: r(fuelTypeScore),
    capacity_scale_score: r(capacityScaleScore),
    longitude_score: r(lonScore),
    latitude_score: r(latScore),
    broadband_score: r(bbScore),
    contamination_score: r(contamScore),
    operational_status_score: r(statusScore),
    flood_zone_score: r(floodScore),
    nearest_sub_name: bestSub.name,
    nearest_sub_distance_miles: r(bestDist),
    nearest_sub_voltage_kv: bestSub.maxVolt,
    nearest_sub_lines: bestSub.lines,
    queue_count_20mi: qwCount,
    queue_mw_20mi: r(qwTotalMW),
  };
}
