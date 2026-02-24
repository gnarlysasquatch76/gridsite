import {
  ScoredSite,
  FLOOD_RISK_STATES,
  MODERATE_FLOOD_STATES,
  BROADBAND_COVERAGE,
} from "./constants";

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

  // Power Access (30%) — distance + voltage
  var distScore = Math.max(0, Math.min(100, 100 - bestDist * 2));
  var voltScore = 60;
  if (bestSub.maxVolt >= 765) voltScore = 100;
  else if (bestSub.maxVolt >= 500) voltScore = 85;
  else if (bestSub.maxVolt >= 345) voltScore = 70;
  var powerAccess = distScore * 0.65 + voltScore * 0.35;

  // Grid Capacity (20%) — lines + queue withdrawals
  var linesScore = Math.max(0, Math.min(100, bestSub.lines / 8 * 100));
  var qwScore: number;
  if (qwCount === 0) {
    qwScore = 30;
  } else {
    var countScore = Math.max(30, Math.min(100, 30 + qwCount * 5));
    var mwBonus = Math.max(0, Math.min(20, qwTotalMW / 5000 * 20));
    qwScore = Math.max(0, Math.min(100, countScore + mwBonus));
  }
  var gridCapacity = linesScore * 0.45 + qwScore * 0.55;

  // Site Characteristics (20%) — unknown site, base 65
  var siteCharacteristics = 65;

  // Connectivity (15%) — longitude proxy + latitude band + broadband
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

  // Risk Factors (15%) — unknown contamination + flood risk
  var floodScore: number;
  if (isCoastalLocation(lat, lng, state)) floodScore = 35;
  else if (MODERATE_FLOOD_STATES.has(state)) floodScore = 65;
  else floodScore = 90;
  var contamScore = 70;
  var riskFactors = contamScore * 0.65 + floodScore * 0.35;

  // Composite
  var composite = powerAccess * 0.30 + gridCapacity * 0.20 + siteCharacteristics * 0.20 + connectivity * 0.15 + riskFactors * 0.15;
  composite = Math.round(Math.max(0, Math.min(100, composite)) * 10) / 10;

  return {
    plant_name: "Custom Location",
    state: state,
    latitude: lat,
    longitude: lng,
    total_capacity_mw: 0,
    fuel_type: "Custom",
    status: "custom",
    composite_score: composite,
    power_access: Math.round(powerAccess * 10) / 10,
    grid_capacity: Math.round(gridCapacity * 10) / 10,
    site_characteristics: siteCharacteristics,
    connectivity: Math.round(connectivity * 10) / 10,
    risk_factors: Math.round(riskFactors * 10) / 10,
    nearest_sub_name: bestSub.name,
    nearest_sub_distance_miles: Math.round(bestDist * 10) / 10,
    nearest_sub_voltage_kv: bestSub.maxVolt,
  };
}
