"use client";

import { useEffect, useRef, useState, useCallback, forwardRef, useImperativeHandle } from "react";
import mapboxgl from "mapbox-gl";
import "mapbox-gl/dist/mapbox-gl.css";
import circle from "@turf/circle";
import booleanIntersects from "@turf/boolean-intersects";
import { point } from "@turf/helpers";
import { haversineDistanceMiles, computeLocationScore, estimateTimeToPower } from "../lib/scoring";
import {
  MAPBOX_TOKEN,
  POWER_PLANTS_SOURCE, POWER_PLANTS_LAYER,
  SUBSTATIONS_SOURCE, SUBSTATIONS_LAYER,
  TRANSMISSION_LINES_SOURCE, TRANSMISSION_LINES_LAYER,
  QUEUE_WITHDRAWALS_SOURCE, QUEUE_WITHDRAWALS_LAYER,
  SCORED_SITES_SOURCE, SCORED_SITES_LAYER,
  RADIUS_CIRCLE_SOURCE, RADIUS_CIRCLE_FILL_LAYER, RADIUS_CIRCLE_OUTLINE_LAYER,
  FLOOD_ZONES_SOURCE, FLOOD_ZONES_LAYER,
  BROADBAND_SOURCE, BROADBAND_LAYER,
  BROWNFIELDS_SOURCE, BROWNFIELDS_LAYER,
  DATA_CENTERS_SOURCE, DATA_CENTERS_LAYER,
  UTILITY_TERRITORIES_SOURCE, UTILITY_TERRITORIES_LAYER, UTILITY_TERRITORIES_OUTLINE_LAYER,
  LMP_NODES_SOURCE, LMP_NODES_LAYER,
  OPPORTUNITIES_SOURCE, OPPORTUNITIES_LAYER,
  OPPORTUNITY_LABELS, OPPORTUNITY_COLORS,
  DIAMOND_ICON, STAR_ICON, TRIANGLE_ICON, SQUARE_ICON,
  type ScoredSite, type ProximityResult, type LayerState,
} from "../lib/constants";

export interface MapHandle {
  flyToSite: (site: ScoredSite) => void;
}

interface MapProps {
  layers: LayerState;
  minMW: number;
  selectedState: string;
  onScoredSitesLoaded: (sites: ScoredSite[]) => void;
  onOpportunitySitesLoaded: (sites: ScoredSite[]) => void;
}

var MapComponent = forwardRef<MapHandle, MapProps>(function MapComponent(props, ref) {
  var { layers, minMW, selectedState, onScoredSitesLoaded, onOpportunitySitesLoaded } = props;

  var mapContainer = useRef<HTMLDivElement>(null);
  var mapRef = useRef<mapboxgl.Map | null>(null);
  var mapLoaded = useRef(false);
  var popupRef = useRef<mapboxgl.Popup | null>(null);

  var [legendOpen, setLegendOpen] = useState(true);
  var [proximityResult, setProximityResult] = useState<ProximityResult | null>(null);
  var [proximityRadius, setProximityRadius] = useState(10);
  var [proximityLoading, setProximityLoading] = useState(false);

  var substationsCache = useRef<GeoJSON.FeatureCollection | null>(null);
  var transmissionLinesCache = useRef<GeoJSON.FeatureCollection | null>(null);
  var queueWithdrawalsCache = useRef<GeoJSON.FeatureCollection | null>(null);
  var lmpNodesCache = useRef<GeoJSON.FeatureCollection | null>(null);

  // --- Proximity Analysis ---

  var clearProximityAnalysis = useCallback(function () {
    var map = mapRef.current;
    if (map) {
      if (map.getLayer(RADIUS_CIRCLE_FILL_LAYER)) map.removeLayer(RADIUS_CIRCLE_FILL_LAYER);
      if (map.getLayer(RADIUS_CIRCLE_OUTLINE_LAYER)) map.removeLayer(RADIUS_CIRCLE_OUTLINE_LAYER);
      if (map.getSource(RADIUS_CIRCLE_SOURCE)) map.removeSource(RADIUS_CIRCLE_SOURCE);
    }
    setProximityResult(null);
  }, []);

  var runProximityAnalysis = useCallback(async function (site: ScoredSite, radiusMiles: number) {
    var map = mapRef.current;
    if (!map) return;

    setProximityLoading(true);

    var center = point([site.longitude, site.latitude]);
    var circlePolygon = circle(center, radiusMiles, { steps: 64, units: "miles" });

    if (map.getSource(RADIUS_CIRCLE_SOURCE)) {
      (map.getSource(RADIUS_CIRCLE_SOURCE) as mapboxgl.GeoJSONSource).setData(circlePolygon);
    } else {
      map.addSource(RADIUS_CIRCLE_SOURCE, { type: "geojson", data: circlePolygon });
      var beforeLayer = map.getLayer(SCORED_SITES_LAYER) ? SCORED_SITES_LAYER : undefined;
      map.addLayer({
        id: RADIUS_CIRCLE_FILL_LAYER, type: "fill", source: RADIUS_CIRCLE_SOURCE,
        paint: { "fill-color": "#eab308", "fill-opacity": 0.08 },
      }, beforeLayer);
      map.addLayer({
        id: RADIUS_CIRCLE_OUTLINE_LAYER, type: "line", source: RADIUS_CIRCLE_SOURCE,
        paint: { "line-color": "#eab308", "line-width": 2, "line-dasharray": [4, 3], "line-opacity": 0.7 },
      }, beforeLayer);
    }

    if (!substationsCache.current) {
      var subRes = await fetch("/data/substations.geojson");
      substationsCache.current = await subRes.json();
    }
    if (!transmissionLinesCache.current) {
      var tlRes = await fetch("/data/transmission-lines.geojson");
      transmissionLinesCache.current = await tlRes.json();
    }
    if (!queueWithdrawalsCache.current) {
      var qwRes = await fetch("/data/queue-withdrawals.geojson");
      queueWithdrawalsCache.current = await qwRes.json();
    }

    // Analyze substations
    var subResult = { total: 0, by500Plus: 0, by345to499: 0, by230to344: 0, byUnder230: 0 };
    var subFeatures = substationsCache.current!.features;
    for (var i = 0; i < subFeatures.length; i++) {
      var sf = subFeatures[i];
      if (sf.geometry.type !== "Point") continue;
      var sCoords = (sf.geometry as GeoJSON.Point).coordinates;
      var dist = haversineDistanceMiles(site.latitude, site.longitude, sCoords[1], sCoords[0]);
      if (dist <= radiusMiles) {
        subResult.total++;
        var maxVolt = sf.properties?.MAX_VOLT != null ? Number(sf.properties.MAX_VOLT) : 0;
        if (maxVolt >= 500) subResult.by500Plus++;
        else if (maxVolt >= 345) subResult.by345to499++;
        else if (maxVolt >= 230) subResult.by230to344++;
        else subResult.byUnder230++;
      }
    }

    // Analyze queue withdrawals
    var qwResult = { total: 0, totalWithdrawnMW: 0 };
    var qwFeatures = queueWithdrawalsCache.current!.features;
    for (var qi = 0; qi < qwFeatures.length; qi++) {
      var qf = qwFeatures[qi];
      if (qf.geometry.type !== "Point") continue;
      var qCoords = (qf.geometry as GeoJSON.Point).coordinates;
      var qDist = haversineDistanceMiles(site.latitude, site.longitude, qCoords[1], qCoords[0]);
      if (qDist <= radiusMiles) {
        qwResult.total++;
        var mw = qf.properties?.total_mw != null ? Number(qf.properties.total_mw) : 0;
        qwResult.totalWithdrawnMW += mw;
      }
    }

    // Analyze transmission lines
    var tlResult = { total: 0, by500Plus: 0, by345to499: 0, by230to344: 0, byUnder230: 0 };
    var degPerMile = 1 / 69.0;
    var latDelta = radiusMiles * degPerMile;
    var lonDelta = radiusMiles * degPerMile / Math.cos(site.latitude * Math.PI / 180);
    var bboxMinLat = site.latitude - latDelta;
    var bboxMaxLat = site.latitude + latDelta;
    var bboxMinLon = site.longitude - lonDelta;
    var bboxMaxLon = site.longitude + lonDelta;

    var tlFeatures = transmissionLinesCache.current!.features;
    for (var ti = 0; ti < tlFeatures.length; ti++) {
      var tf = tlFeatures[ti];
      var tGeom = tf.geometry;
      if (tGeom.type !== "LineString" && tGeom.type !== "MultiLineString") continue;

      var coords: number[][] = [];
      if (tGeom.type === "LineString") {
        coords = (tGeom as GeoJSON.LineString).coordinates;
      } else {
        var multiCoords = (tGeom as GeoJSON.MultiLineString).coordinates;
        for (var mi = 0; mi < multiCoords.length; mi++) {
          coords = coords.concat(multiCoords[mi]);
        }
      }

      var inBbox = false;
      for (var ci = 0; ci < coords.length; ci++) {
        if (coords[ci][0] >= bboxMinLon && coords[ci][0] <= bboxMaxLon &&
            coords[ci][1] >= bboxMinLat && coords[ci][1] <= bboxMaxLat) {
          inBbox = true;
          break;
        }
      }
      if (!inBbox) continue;

      if (booleanIntersects(tf as any, circlePolygon)) {
        tlResult.total++;
        var voltage = tf.properties?.VOLTAGE != null ? Number(tf.properties.VOLTAGE) : 0;
        if (voltage >= 500) tlResult.by500Plus++;
        else if (voltage >= 345) tlResult.by345to499++;
        else if (voltage >= 230) tlResult.by230to344++;
        else tlResult.byUnder230++;
      }
    }

    setProximityResult({ site, radiusMiles, substations: subResult, transmissionLines: tlResult, queueWithdrawals: qwResult });
    setProximityLoading(false);
  }, []);

  // --- Popup Builders ---

  var buildPopupHTML = useCallback(function (props: Record<string, any>): string {
    var statusColors: Record<string, string> = { operating: "#22c55e", retiring: "#f97316", retired: "#ef4444" };
    var color = statusColors[props.status] || "#94a3b8";
    var statusLabel = props.status.charAt(0).toUpperCase() + props.status.slice(1);

    var html = "<div style=\"font-family:system-ui,sans-serif;padding:4px;min-width:220px;\">" +
      "<div style=\"font-size:15px;font-weight:700;color:#1B2A4A;margin-bottom:2px;\">" + props.plant_name + "</div>" +
      "<div style=\"font-size:12px;color:#64748b;margin-bottom:8px;\">" + props.state + "</div>" +
      "<div style=\"display:flex;gap:8px;margin-bottom:6px;\">" +
        "<span style=\"background:" + color + ";color:white;border-radius:4px;padding:2px 8px;font-size:11px;font-weight:600;\">" + statusLabel + "</span>" +
      "</div>" +
      "<div style=\"border-top:1px solid #e2e8f0;padding-top:6px;font-size:12px;color:#334155;\">" +
        "<div style=\"display:flex;justify-content:space-between;margin:3px 0;\"><span>Capacity</span><strong>" + props.total_capacity_mw.toLocaleString() + " MW</strong></div>" +
        "<div style=\"display:flex;justify-content:space-between;margin:3px 0;\"><span>Fuel Type</span><strong>" + props.fuel_type + "</strong></div>";
    if (props.planned_retirement_date) {
      html += "<div style=\"display:flex;justify-content:space-between;margin:3px 0;\"><span>Planned Retirement</span><strong>" + props.planned_retirement_date + "</strong></div>";
    }
    html += "</div></div>";
    return html;
  }, []);

  var buildSubstationPopupHTML = useCallback(function (props: Record<string, any>): string {
    var name = props.NAME || "Unknown";
    var city = props.CITY || "";
    var state = props.STATE || "";
    var location = [city, state].filter(Boolean).join(", ");
    var maxVoltVal = props.MAX_VOLT != null ? Number(props.MAX_VOLT) : null;
    var minVolt = props.MIN_VOLT != null ? Number(props.MIN_VOLT) : null;
    var status = props.STATUS || "Unknown";
    var type = props.TYPE || "";
    var lines = props.LINES != null ? Number(props.LINES) : null;

    var voltColor = "#22d3ee";
    if (maxVoltVal != null && maxVoltVal >= 345) voltColor = "#a78bfa";
    else if (maxVoltVal != null && maxVoltVal >= 230) voltColor = "#38bdf8";

    var html = "<div style=\"font-family:system-ui,sans-serif;padding:4px;min-width:220px;\">" +
      "<div style=\"font-size:15px;font-weight:700;color:#1B2A4A;margin-bottom:2px;\">" + name + "</div>" +
      "<div style=\"font-size:12px;color:#64748b;margin-bottom:8px;\">" + location + "</div>" +
      "<div style=\"display:flex;gap:8px;margin-bottom:6px;\">" +
        "<span style=\"background:" + voltColor + ";color:#0f172a;border-radius:4px;padding:2px 8px;font-size:11px;font-weight:600;\">" +
          (maxVoltVal != null ? maxVoltVal + " kV" : "N/A") + "</span>" +
        (type ? "<span style=\"background:#334155;color:white;border-radius:4px;padding:2px 8px;font-size:11px;font-weight:600;\">" + type + "</span>" : "") +
      "</div>" +
      "<div style=\"border-top:1px solid #e2e8f0;padding-top:6px;font-size:12px;color:#334155;\">" +
        "<div style=\"display:flex;justify-content:space-between;margin:3px 0;\"><span>Status</span><strong>" + status + "</strong></div>";
    if (maxVoltVal != null) {
      html += "<div style=\"display:flex;justify-content:space-between;margin:3px 0;\"><span>Max Voltage</span><strong>" + maxVoltVal + " kV</strong></div>";
    }
    if (minVolt != null) {
      html += "<div style=\"display:flex;justify-content:space-between;margin:3px 0;\"><span>Min Voltage</span><strong>" + minVolt + " kV</strong></div>";
    }
    if (lines != null) {
      html += "<div style=\"display:flex;justify-content:space-between;margin:3px 0;\"><span>Connected Lines</span><strong>" + lines + "</strong></div>";
    }
    html += "</div></div>";
    return html;
  }, []);

  var buildTransmissionLinePopupHTML = useCallback(function (props: Record<string, any>): string {
    var voltageVal = props.VOLTAGE != null ? Number(props.VOLTAGE) : null;
    var voltClass = props.VOLT_CLASS || "";
    var owner = props.OWNER || "Unknown";
    var status = props.STATUS || "Unknown";
    var type = props.TYPE || "";
    var sub1 = props.SUB_1 || "";
    var sub2 = props.SUB_2 || "";

    var voltColor = "#22d3ee";
    if (voltageVal != null && voltageVal >= 500) voltColor = "#a78bfa";
    else if (voltageVal != null && voltageVal >= 345) voltColor = "#818cf8";
    else if (voltageVal != null && voltageVal >= 230) voltColor = "#38bdf8";

    var html = "<div style=\"font-family:system-ui,sans-serif;padding:4px;min-width:220px;\">" +
      "<div style=\"font-size:15px;font-weight:700;color:#1B2A4A;margin-bottom:2px;\">Transmission Line</div>" +
      "<div style=\"display:flex;gap:8px;margin-bottom:6px;\">" +
        "<span style=\"background:" + voltColor + ";color:#0f172a;border-radius:4px;padding:2px 8px;font-size:11px;font-weight:600;\">" +
          (voltageVal != null ? voltageVal + " kV" : voltClass) + "</span>" +
        (type ? "<span style=\"background:#334155;color:white;border-radius:4px;padding:2px 8px;font-size:11px;font-weight:600;\">" + type + "</span>" : "") +
      "</div>" +
      "<div style=\"border-top:1px solid #e2e8f0;padding-top:6px;font-size:12px;color:#334155;\">" +
        "<div style=\"display:flex;justify-content:space-between;margin:3px 0;\"><span>Owner</span><strong>" + owner + "</strong></div>" +
        "<div style=\"display:flex;justify-content:space-between;margin:3px 0;\"><span>Status</span><strong>" + status + "</strong></div>";
    if (sub1 || sub2) {
      var route = [sub1, sub2].filter(Boolean).join(" \u2192 ");
      html += "<div style=\"display:flex;justify-content:space-between;margin:3px 0;\"><span>Route</span><strong>" + route + "</strong></div>";
    }
    html += "</div></div>";
    return html;
  }, []);

  var buildQueuePopupHTML = useCallback(function (props: Record<string, any>): string {
    var name = props.project_name || props.q_id || "Unknown";
    var county = props.county || "";
    var state = props.state || "";
    var location = [county, state].filter(Boolean).join(", ");
    var totalMW = props.total_mw != null ? Number(props.total_mw) : null;
    var fuelType = props.fuel_type || "Unknown";
    var entity = props.entity || "";
    var poi = props.poi_name || "";
    var qDate = props.q_date || "";
    var wdDate = props.wd_date || "";

    var html = "<div style=\"font-family:system-ui,sans-serif;padding:4px;min-width:220px;\">" +
      "<div style=\"font-size:15px;font-weight:700;color:#1B2A4A;margin-bottom:2px;\">" + name + "</div>" +
      "<div style=\"font-size:12px;color:#64748b;margin-bottom:8px;\">" + location + "</div>" +
      "<div style=\"display:flex;gap:8px;margin-bottom:6px;\">" +
        "<span style=\"background:#f97316;color:white;border-radius:4px;padding:2px 8px;font-size:11px;font-weight:600;\">Withdrawn</span>" +
        "<span style=\"background:#334155;color:white;border-radius:4px;padding:2px 8px;font-size:11px;font-weight:600;\">" + fuelType + "</span>" +
      "</div>" +
      "<div style=\"border-top:1px solid #e2e8f0;padding-top:6px;font-size:12px;color:#334155;\">";
    if (totalMW != null) {
      html += "<div style=\"display:flex;justify-content:space-between;margin:3px 0;\"><span>Capacity</span><strong>" + totalMW.toLocaleString() + " MW</strong></div>";
    }
    if (entity) {
      html += "<div style=\"display:flex;justify-content:space-between;margin:3px 0;\"><span>ISO/RTO</span><strong>" + entity + "</strong></div>";
    }
    if (poi) {
      html += "<div style=\"display:flex;justify-content:space-between;margin:3px 0;\"><span>POI</span><strong>" + poi + "</strong></div>";
    }
    if (qDate) {
      html += "<div style=\"display:flex;justify-content:space-between;margin:3px 0;\"><span>Queue Date</span><strong>" + qDate + "</strong></div>";
    }
    if (wdDate) {
      html += "<div style=\"display:flex;justify-content:space-between;margin:3px 0;\"><span>Withdrawn</span><strong>" + wdDate + "</strong></div>";
    }
    html += "</div></div>";
    return html;
  }, []);

  var buildScoredSitePopupHTML = useCallback(function (s: ScoredSite): string {
    function bar(label: string, value: number, weight: string): string {
      var barColor = value >= 80 ? "#eab308" : value >= 60 ? "#a3a3a3" : "#78716c";
      return "<div style=\"margin:3px 0;\">" +
        "<div style=\"display:flex;justify-content:space-between;font-size:11px;\">" +
          "<span>" + label + " <span style=\"color:#94a3b8;\">(" + weight + ")</span></span>" +
          "<strong style=\"color:" + barColor + ";\">" + value + "</strong>" +
        "</div>" +
        "<div style=\"background:#1e293b;border-radius:3px;height:5px;margin-top:2px;\">" +
          "<div style=\"background:" + barColor + ";border-radius:3px;height:5px;width:" + value + "%;\"></div>" +
        "</div></div>";
    }

    var ttp = estimateTimeToPower(s);
    var ttpColor = ttp.tier === "green" ? "#10b981" : ttp.tier === "yellow" ? "#f59e0b" : "#ef4444";
    var ttpBadge = "<span style=\"background:" + ttpColor + ";color:" + (ttp.tier === "red" ? "#fff" : "#000") + ";border-radius:4px;padding:2px 6px;font-size:10px;font-weight:700;margin-left:6px;\">" + ttp.label + "</span>";

    return "<div style=\"font-family:system-ui,sans-serif;padding:4px;min-width:260px;\">" +
      "<div style=\"display:flex;justify-content:space-between;align-items:start;margin-bottom:4px;\">" +
        "<div>" +
          "<div style=\"font-size:15px;font-weight:700;color:#1B2A4A;\">" + s.plant_name + "</div>" +
          "<div style=\"font-size:12px;color:#64748b;\">" + (s.total_capacity_mw > 0 ? s.state + " &middot; " + s.total_capacity_mw.toLocaleString() + " MW" : s.state + " &middot; " + s.latitude.toFixed(4) + "&deg;, " + s.longitude.toFixed(4) + "&deg;") + "</div>" +
        "</div>" +
        "<div style=\"background:#eab308;color:#0f172a;border-radius:6px;padding:4px 10px;font-size:18px;font-weight:bold;min-width:44px;text-align:center;\">" + s.composite_score + "</div>" +
      "</div>" +
      (s.fuel_type === "Custom" ? "<div style=\"font-size:11px;color:#10b981;margin-bottom:6px;\">Right-click scored location" + ttpBadge + "</div>" : "<div style=\"font-size:11px;color:#64748b;margin-bottom:6px;\">" + s.fuel_type + " &middot; " + s.status + ttpBadge + "</div>") +
      "<div style=\"border-top:1px solid #e2e8f0;padding-top:6px;\">" +
        bar("Time to Power", s.time_to_power, "50%") +
        bar("Site Readiness", s.site_readiness, "20%") +
        bar("Connectivity", s.connectivity, "15%") +
        bar("Risk Factors", s.risk_factors, "15%") +
      "</div>" +
      "<div style=\"border-top:1px solid #e2e8f0;margin-top:6px;padding-top:6px;font-size:11px;color:#64748b;\">" +
        "<div style=\"display:flex;justify-content:space-between;margin:2px 0;\"><span>Nearest 345kV+ Sub</span><strong style=\"color:#334155;\">" + s.nearest_sub_name + "</strong></div>" +
        "<div style=\"display:flex;justify-content:space-between;margin:2px 0;\"><span>Distance</span><strong style=\"color:#334155;\">" + s.nearest_sub_distance_miles + " mi</strong></div>" +
        "<div style=\"display:flex;justify-content:space-between;margin:2px 0;\"><span>Sub Voltage</span><strong style=\"color:#334155;\">" + s.nearest_sub_voltage_kv + " kV</strong></div>" +
      "</div></div>";
  }, []);

  var buildLmpPopupHTML = useCallback(function (props: Record<string, any>): string {
    var name = props.name || "Unknown";
    var iso = props.iso || "";
    var avgLmp = props.avg_lmp != null ? Number(props.avg_lmp) : 0;
    var lmpClass = props.lmp_class || "moderate";
    var classColor = lmpClass === "low" ? "#22c55e" : lmpClass === "moderate" ? "#f59e0b" : "#ef4444";
    var classLabel = lmpClass === "low" ? "Low (Headroom)" : lmpClass === "moderate" ? "Moderate" : "High (Congestion)";

    return "<div style=\"font-family:system-ui,sans-serif;padding:4px;min-width:220px;\">" +
      "<div style=\"font-size:15px;font-weight:700;color:#1B2A4A;margin-bottom:2px;\">" + name + "</div>" +
      "<div style=\"font-size:12px;color:#64748b;margin-bottom:8px;\">" + iso + "</div>" +
      "<div style=\"display:flex;gap:8px;margin-bottom:6px;\">" +
        "<span style=\"background:" + classColor + ";color:" + (lmpClass === "high" ? "#fff" : "#000") + ";border-radius:4px;padding:2px 8px;font-size:11px;font-weight:600;\">" + classLabel + "</span>" +
      "</div>" +
      "<div style=\"border-top:1px solid #e2e8f0;padding-top:6px;font-size:12px;color:#334155;\">" +
        "<div style=\"display:flex;justify-content:space-between;margin:3px 0;\"><span>Avg LMP</span><strong>$" + avgLmp.toFixed(1) + "/MWh</strong></div>" +
        "<div style=\"display:flex;justify-content:space-between;margin:3px 0;\"><span>Avg LMP</span><strong>" + (avgLmp * 0.1).toFixed(1) + " &cent;/kWh</strong></div>" +
      "</div></div>";
  }, []);

  var buildOpportunityPopupHTML = useCallback(function (s: ScoredSite): string {
    var oppType = s.opportunity_type || "";
    var oppLabel = OPPORTUNITY_LABELS[oppType] || oppType;
    var oppColor = OPPORTUNITY_COLORS[oppType] || "#94a3b8";

    function bar(label: string, value: number, weight: string): string {
      var barColor = value >= 80 ? "#eab308" : value >= 60 ? "#a3a3a3" : "#78716c";
      return "<div style=\"margin:3px 0;\">" +
        "<div style=\"display:flex;justify-content:space-between;font-size:11px;\">" +
          "<span>" + label + " <span style=\"color:#94a3b8;\">(" + weight + ")</span></span>" +
          "<strong style=\"color:" + barColor + ";\">" + value + "</strong>" +
        "</div>" +
        "<div style=\"background:#1e293b;border-radius:3px;height:5px;margin-top:2px;\">" +
          "<div style=\"background:" + barColor + ";border-radius:3px;height:5px;width:" + value + "%;\"></div>" +
        "</div></div>";
    }

    var ttp = estimateTimeToPower(s);
    var ttpColor = ttp.tier === "green" ? "#10b981" : ttp.tier === "yellow" ? "#f59e0b" : "#ef4444";

    return "<div style=\"font-family:system-ui,sans-serif;padding:4px;min-width:260px;\">" +
      "<div style=\"display:flex;justify-content:space-between;align-items:start;margin-bottom:4px;\">" +
        "<div>" +
          "<div style=\"font-size:15px;font-weight:700;color:#1B2A4A;\">" + s.plant_name + "</div>" +
          "<div style=\"font-size:12px;color:#64748b;\">" + s.state + (s.total_capacity_mw > 0 ? " &middot; " + s.total_capacity_mw.toLocaleString() + " MW" : "") + "</div>" +
        "</div>" +
        "<div style=\"background:#eab308;color:#0f172a;border-radius:6px;padding:4px 10px;font-size:18px;font-weight:bold;min-width:44px;text-align:center;\">" + s.composite_score + "</div>" +
      "</div>" +
      "<div style=\"display:flex;gap:6px;margin-bottom:6px;\">" +
        "<span style=\"background:" + oppColor + ";color:" + (oppType === "retired_plant" ? "#fff" : "#000") + ";border-radius:4px;padding:2px 8px;font-size:11px;font-weight:600;\">" + oppLabel + "</span>" +
        "<span style=\"background:" + ttpColor + ";color:" + (ttp.tier === "red" ? "#fff" : "#000") + ";border-radius:4px;padding:2px 6px;font-size:10px;font-weight:700;\">" + ttp.label + "</span>" +
      "</div>" +
      (s.qualifying_substation ? "<div style=\"font-size:11px;color:#64748b;margin-bottom:6px;\">Near " + s.qualifying_substation + " (" + (s.qualifying_sub_kv || "") + " kV)</div>" : "") +
      "<div style=\"border-top:1px solid #e2e8f0;padding-top:6px;\">" +
        bar("Time to Power", s.time_to_power, "50%") +
        bar("Site Readiness", s.site_readiness, "20%") +
        bar("Connectivity", s.connectivity, "15%") +
        bar("Risk Factors", s.risk_factors, "15%") +
      "</div></div>";
  }, []);

  // --- Score any location on right-click ---

  var scoreLocation = useCallback(async function (lng: number, lat: number) {
    var map = mapRef.current;
    if (!map) return;

    if (!substationsCache.current) {
      var subRes = await fetch("/data/substations.geojson");
      substationsCache.current = await subRes.json();
    }
    if (!queueWithdrawalsCache.current) {
      var qwRes = await fetch("/data/queue-withdrawals.geojson");
      queueWithdrawalsCache.current = await qwRes.json();
    }
    if (!lmpNodesCache.current) {
      var lmpRes = await fetch("/data/lmp-nodes.geojson");
      lmpNodesCache.current = await lmpRes.json();
    }

    var site = computeLocationScore(lng, lat, substationsCache.current!, queueWithdrawalsCache.current!, lmpNodesCache.current);
    if (!site) return;

    if (popupRef.current) popupRef.current.remove();
    popupRef.current = new mapboxgl.Popup({ offset: 14, maxWidth: "340px" })
      .setLngLat([lng, lat])
      .setHTML(buildScoredSitePopupHTML(site))
      .addTo(map);

    runProximityAnalysis(site, proximityRadius);
  }, [buildScoredSitePopupHTML, runProximityAnalysis, proximityRadius]);

  var scoreLocationRef = useRef<(lng: number, lat: number) => void>(function () {});
  scoreLocationRef.current = scoreLocation;

  // --- Fly to site (exposed via ref) ---

  var flyToSite = useCallback(function (site: ScoredSite) {
    var map = mapRef.current;
    if (!map) return;

    map.flyTo({ center: [site.longitude, site.latitude], zoom: 10, duration: 1500 });

    if (popupRef.current) popupRef.current.remove();
    map.once("moveend", function () {
      if (!mapRef.current) return;
      popupRef.current = new mapboxgl.Popup({ offset: 14, maxWidth: "340px" })
        .setLngLat([site.longitude, site.latitude])
        .setHTML(buildScoredSitePopupHTML(site))
        .addTo(mapRef.current);
    });

    runProximityAnalysis(site, proximityRadius);
  }, [buildScoredSitePopupHTML, runProximityAnalysis, proximityRadius]);

  useImperativeHandle(ref, function () {
    return { flyToSite: flyToSite };
  }, [flyToSite]);

  // --- Initialize map ---

  useEffect(function () {
    if (!mapContainer.current) return;

    var map = new mapboxgl.Map({
      container: mapContainer.current,
      style: "mapbox://styles/mapbox/dark-v11",
      center: [-98.5, 39.8],
      zoom: 4,
      accessToken: MAPBOX_TOKEN,
    });

    map.addControl(new mapboxgl.NavigationControl());

    map.on("load", function () {
      // Diamond icon
      var size = 20;
      var canvas = document.createElement("canvas");
      canvas.width = size; canvas.height = size;
      var ctx = canvas.getContext("2d");
      if (ctx) {
        ctx.beginPath();
        ctx.moveTo(size / 2, 1); ctx.lineTo(size - 1, size / 2);
        ctx.lineTo(size / 2, size - 1); ctx.lineTo(1, size / 2);
        ctx.closePath(); ctx.fillStyle = "#ffffff"; ctx.fill();
        map.addImage(DIAMOND_ICON, ctx.getImageData(0, 0, size, size), { sdf: true });
      }

      // Star icon
      var starSize = 24;
      var starCanvas = document.createElement("canvas");
      starCanvas.width = starSize; starCanvas.height = starSize;
      var starCtx = starCanvas.getContext("2d");
      if (starCtx) {
        var cx = starSize / 2; var cy = starSize / 2;
        var outerR = starSize / 2 - 1; var innerR = outerR * 0.4;
        starCtx.beginPath();
        for (var si = 0; si < 10; si++) {
          var r = si % 2 === 0 ? outerR : innerR;
          var angle = (Math.PI / 2 * -1) + (Math.PI / 5) * si;
          var px = cx + r * Math.cos(angle); var py = cy + r * Math.sin(angle);
          if (si === 0) starCtx.moveTo(px, py); else starCtx.lineTo(px, py);
        }
        starCtx.closePath(); starCtx.fillStyle = "#ffffff"; starCtx.fill();
        map.addImage(STAR_ICON, starCtx.getImageData(0, 0, starSize, starSize), { sdf: true });
      }

      // Triangle icon
      var triSize = 18;
      var triCanvas = document.createElement("canvas");
      triCanvas.width = triSize; triCanvas.height = triSize;
      var triCtx = triCanvas.getContext("2d");
      if (triCtx) {
        triCtx.beginPath();
        triCtx.moveTo(triSize / 2, 1); triCtx.lineTo(triSize - 1, triSize - 1); triCtx.lineTo(1, triSize - 1);
        triCtx.closePath(); triCtx.fillStyle = "#ffffff"; triCtx.fill();
        map.addImage(TRIANGLE_ICON, triCtx.getImageData(0, 0, triSize, triSize), { sdf: true });
      }

      // Square icon
      var sqSize = 16;
      var sqCanvas = document.createElement("canvas");
      sqCanvas.width = sqSize; sqCanvas.height = sqSize;
      var sqCtx = sqCanvas.getContext("2d");
      if (sqCtx) {
        sqCtx.fillStyle = "#ffffff"; sqCtx.fillRect(2, 2, sqSize - 4, sqSize - 4);
        map.addImage(SQUARE_ICON, sqCtx.getImageData(0, 0, sqSize, sqSize), { sdf: true });
      }

      map.on("contextmenu", function (e) {
        e.preventDefault();
        scoreLocationRef.current(e.lngLat.lng, e.lngLat.lat);
      });

      mapLoaded.current = true;
    });

    mapRef.current = map;
    return function () { mapLoaded.current = false; mapRef.current = null; map.remove(); };
  }, []);

  // --- Layer toggle effects ---

  useEffect(function () {
    var map = mapRef.current;
    if (!map) return;
    function setup() {
      if (!map) return;
      if (map.getLayer(POWER_PLANTS_LAYER)) {
        map.setLayoutProperty(POWER_PLANTS_LAYER, "visibility", layers.powerPlants ? "visible" : "none");
        return;
      }
      if (!layers.powerPlants) return;
      map.addSource(POWER_PLANTS_SOURCE, { type: "geojson", data: "/data/power-plants.geojson" });
      map.addLayer({
        id: POWER_PLANTS_LAYER, type: "circle", source: POWER_PLANTS_SOURCE,
        paint: {
          "circle-color": ["match", ["get", "status"], "operating", "#22c55e", "retiring", "#f97316", "retired", "#ef4444", "#94a3b8"],
          "circle-radius": ["interpolate", ["linear"], ["get", "total_capacity_mw"], 50, 3, 500, 7, 2000, 12, 5000, 18],
          "circle-opacity": 0.85, "circle-stroke-color": "#ffffff", "circle-stroke-width": 0.5,
        },
      });
      map.on("click", POWER_PLANTS_LAYER, function (e) {
        if (!e.features || e.features.length === 0) return;
        var feature = e.features[0];
        var coords = (feature.geometry as GeoJSON.Point).coordinates.slice() as [number, number];
        var p = feature.properties as Record<string, any>;
        if (typeof p.total_capacity_mw === "string") p.total_capacity_mw = parseFloat(p.total_capacity_mw);
        if (popupRef.current) popupRef.current.remove();
        popupRef.current = new mapboxgl.Popup({ offset: 12, maxWidth: "300px" }).setLngLat(coords).setHTML(buildPopupHTML(p)).addTo(map!);
      });
      map.on("mouseenter", POWER_PLANTS_LAYER, function () { map!.getCanvas().style.cursor = "pointer"; });
      map.on("mouseleave", POWER_PLANTS_LAYER, function () { map!.getCanvas().style.cursor = ""; });
    }
    if (mapLoaded.current) setup(); else map.on("load", setup);
  }, [layers.powerPlants, buildPopupHTML]);

  useEffect(function () {
    var map = mapRef.current;
    if (!map) return;
    function setup() {
      if (!map) return;
      if (map.getLayer(SUBSTATIONS_LAYER)) {
        map.setLayoutProperty(SUBSTATIONS_LAYER, "visibility", layers.substations ? "visible" : "none");
        return;
      }
      if (!layers.substations) return;
      map.addSource(SUBSTATIONS_SOURCE, { type: "geojson", data: "/data/substations.geojson" });
      map.addLayer({
        id: SUBSTATIONS_LAYER, type: "symbol", source: SUBSTATIONS_SOURCE,
        layout: {
          "icon-image": DIAMOND_ICON,
          "icon-size": ["step", ["get", "MAX_VOLT"], 0.4, 230, 0.55, 345, 0.7, 500, 0.9],
          "icon-allow-overlap": true,
        },
        paint: {
          "icon-color": ["step", ["get", "MAX_VOLT"], "#22d3ee", 230, "#38bdf8", 345, "#818cf8", 500, "#a78bfa"],
          "icon-opacity": 0.9,
        },
      });
      map.on("click", SUBSTATIONS_LAYER, function (e) {
        if (!e.features || e.features.length === 0) return;
        var feature = e.features[0];
        var coords = (feature.geometry as GeoJSON.Point).coordinates.slice() as [number, number];
        var p = feature.properties as Record<string, any>;
        if (typeof p.MAX_VOLT === "string") p.MAX_VOLT = parseFloat(p.MAX_VOLT);
        if (typeof p.MIN_VOLT === "string") p.MIN_VOLT = parseFloat(p.MIN_VOLT);
        if (typeof p.LINES === "string") p.LINES = parseFloat(p.LINES);
        if (popupRef.current) popupRef.current.remove();
        popupRef.current = new mapboxgl.Popup({ offset: 12, maxWidth: "300px" }).setLngLat(coords).setHTML(buildSubstationPopupHTML(p)).addTo(map!);
      });
      map.on("mouseenter", SUBSTATIONS_LAYER, function () { map!.getCanvas().style.cursor = "pointer"; });
      map.on("mouseleave", SUBSTATIONS_LAYER, function () { map!.getCanvas().style.cursor = ""; });
    }
    if (mapLoaded.current) setup(); else map.on("load", setup);
  }, [layers.substations, buildSubstationPopupHTML]);

  useEffect(function () {
    var map = mapRef.current;
    if (!map) return;
    function setup() {
      if (!map) return;
      if (map.getLayer(TRANSMISSION_LINES_LAYER)) {
        map.setLayoutProperty(TRANSMISSION_LINES_LAYER, "visibility", layers.transmissionLines ? "visible" : "none");
        return;
      }
      if (!layers.transmissionLines) return;
      map.addSource(TRANSMISSION_LINES_SOURCE, { type: "geojson", data: "/data/transmission-lines.geojson" });
      map.addLayer({
        id: TRANSMISSION_LINES_LAYER, type: "line", source: TRANSMISSION_LINES_SOURCE,
        layout: { "line-cap": "round", "line-join": "round" },
        paint: {
          "line-color": ["step", ["get", "VOLTAGE"], "#22d3ee", 230, "#38bdf8", 345, "#818cf8", 500, "#a78bfa"],
          "line-width": ["step", ["get", "VOLTAGE"], 1, 230, 1.5, 345, 2.5, 500, 3.5],
          "line-opacity": 0.7,
        },
      });
      map.on("click", TRANSMISSION_LINES_LAYER, function (e) {
        if (!e.features || e.features.length === 0) return;
        var p = e.features[0].properties as Record<string, any>;
        if (typeof p.VOLTAGE === "string") p.VOLTAGE = parseFloat(p.VOLTAGE);
        if (popupRef.current) popupRef.current.remove();
        popupRef.current = new mapboxgl.Popup({ offset: 12, maxWidth: "320px" }).setLngLat(e.lngLat).setHTML(buildTransmissionLinePopupHTML(p)).addTo(map!);
      });
      map.on("mouseenter", TRANSMISSION_LINES_LAYER, function () { map!.getCanvas().style.cursor = "pointer"; });
      map.on("mouseleave", TRANSMISSION_LINES_LAYER, function () { map!.getCanvas().style.cursor = ""; });
    }
    if (mapLoaded.current) setup(); else map.on("load", setup);
  }, [layers.transmissionLines, buildTransmissionLinePopupHTML]);

  useEffect(function () {
    var map = mapRef.current;
    if (!map) return;
    function setup() {
      if (!map) return;
      if (map.getLayer(QUEUE_WITHDRAWALS_LAYER)) {
        map.setLayoutProperty(QUEUE_WITHDRAWALS_LAYER, "visibility", layers.queueWithdrawals ? "visible" : "none");
        return;
      }
      if (!layers.queueWithdrawals) return;
      map.addSource(QUEUE_WITHDRAWALS_SOURCE, { type: "geojson", data: "/data/queue-withdrawals.geojson" });
      map.addLayer({
        id: QUEUE_WITHDRAWALS_LAYER, type: "symbol", source: QUEUE_WITHDRAWALS_SOURCE,
        layout: {
          "icon-image": TRIANGLE_ICON,
          "icon-size": ["interpolate", ["linear"], ["get", "total_mw"], 50, 0.4, 500, 0.7, 2000, 1.0],
          "icon-allow-overlap": true,
        },
        paint: { "icon-color": "#f97316", "icon-opacity": 0.85 },
      });
      map.on("click", QUEUE_WITHDRAWALS_LAYER, function (e) {
        if (!e.features || e.features.length === 0) return;
        var feature = e.features[0];
        var coords = (feature.geometry as GeoJSON.Point).coordinates.slice() as [number, number];
        var p = feature.properties as Record<string, any>;
        if (typeof p.total_mw === "string") p.total_mw = parseFloat(p.total_mw);
        if (popupRef.current) popupRef.current.remove();
        popupRef.current = new mapboxgl.Popup({ offset: 12, maxWidth: "320px" }).setLngLat(coords).setHTML(buildQueuePopupHTML(p)).addTo(map!);
      });
      map.on("mouseenter", QUEUE_WITHDRAWALS_LAYER, function () { map!.getCanvas().style.cursor = "pointer"; });
      map.on("mouseleave", QUEUE_WITHDRAWALS_LAYER, function () { map!.getCanvas().style.cursor = ""; });
    }
    if (mapLoaded.current) setup(); else map.on("load", setup);
  }, [layers.queueWithdrawals, buildQueuePopupHTML]);

  useEffect(function () {
    var map = mapRef.current;
    if (!map) return;
    function setup() {
      if (!map) return;
      if (map.getLayer(FLOOD_ZONES_LAYER)) {
        map.setLayoutProperty(FLOOD_ZONES_LAYER, "visibility", layers.floodZones ? "visible" : "none");
        return;
      }
      if (!layers.floodZones) return;
      map.addSource(FLOOD_ZONES_SOURCE, {
        type: "raster",
        tiles: ["https://hazards.fema.gov/arcgis/rest/services/public/NFHL/MapServer/export?bbox={bbox-epsg-3857}&bboxSR=3857&imageSR=3857&size=256,256&layers=show:28&format=png32&transparent=true&f=image"],
        tileSize: 256,
      });
      var beforeLayer: string | undefined;
      if (map.getLayer(POWER_PLANTS_LAYER)) beforeLayer = POWER_PLANTS_LAYER;
      else if (map.getLayer(TRANSMISSION_LINES_LAYER)) beforeLayer = TRANSMISSION_LINES_LAYER;
      else if (map.getLayer(SUBSTATIONS_LAYER)) beforeLayer = SUBSTATIONS_LAYER;
      else if (map.getLayer(QUEUE_WITHDRAWALS_LAYER)) beforeLayer = QUEUE_WITHDRAWALS_LAYER;
      else if (map.getLayer(SCORED_SITES_LAYER)) beforeLayer = SCORED_SITES_LAYER;
      map.addLayer({ id: FLOOD_ZONES_LAYER, type: "raster", source: FLOOD_ZONES_SOURCE, paint: { "raster-opacity": 0.3 } }, beforeLayer);
    }
    if (mapLoaded.current) setup(); else map.on("load", setup);
  }, [layers.floodZones]);

  useEffect(function () {
    var map = mapRef.current;
    if (!map) return;
    function setup() {
      if (!map) return;
      if (map.getLayer(BROADBAND_LAYER)) {
        map.setLayoutProperty(BROADBAND_LAYER, "visibility", layers.broadband ? "visible" : "none");
        return;
      }
      if (!layers.broadband) return;
      map.addSource(BROADBAND_SOURCE, {
        type: "raster",
        tiles: ["https://mtgis-server.geo.census.gov/arcgis/rest/services/Broadband_Indicator_2/MapServer/export?bbox={bbox-epsg-3857}&bboxSR=3857&imageSR=3857&size=256,256&format=png32&transparent=true&f=image"],
        tileSize: 256,
      });
      var beforeLayer: string | undefined;
      if (map.getLayer(FLOOD_ZONES_LAYER)) beforeLayer = FLOOD_ZONES_LAYER;
      else if (map.getLayer(POWER_PLANTS_LAYER)) beforeLayer = POWER_PLANTS_LAYER;
      else if (map.getLayer(TRANSMISSION_LINES_LAYER)) beforeLayer = TRANSMISSION_LINES_LAYER;
      else if (map.getLayer(SUBSTATIONS_LAYER)) beforeLayer = SUBSTATIONS_LAYER;
      else if (map.getLayer(QUEUE_WITHDRAWALS_LAYER)) beforeLayer = QUEUE_WITHDRAWALS_LAYER;
      else if (map.getLayer(SCORED_SITES_LAYER)) beforeLayer = SCORED_SITES_LAYER;
      map.addLayer({ id: BROADBAND_LAYER, type: "raster", source: BROADBAND_SOURCE, paint: { "raster-opacity": 0.35 } }, beforeLayer);
    }
    if (mapLoaded.current) setup(); else map.on("load", setup);
  }, [layers.broadband]);

  useEffect(function () {
    var map = mapRef.current;
    if (!map) return;
    function setup() {
      if (!map) return;
      if (map.getLayer(BROWNFIELDS_LAYER)) {
        map.setLayoutProperty(BROWNFIELDS_LAYER, "visibility", layers.brownfields ? "visible" : "none");
        return;
      }
      if (!layers.brownfields) return;
      map.addSource(BROWNFIELDS_SOURCE, { type: "geojson", data: "/data/epa-brownfields.geojson" });
      map.addLayer({
        id: BROWNFIELDS_LAYER, type: "circle", source: BROWNFIELDS_SOURCE,
        paint: {
          "circle-color": "#a0845c",
          "circle-radius": ["interpolate", ["linear"], ["zoom"], 4, 1.5, 8, 3, 12, 5],
          "circle-opacity": 0.75, "circle-stroke-color": "#d4a853", "circle-stroke-width": 0.5,
        },
      });
      map.on("click", BROWNFIELDS_LAYER, function (e) {
        if (!e.features || e.features.length === 0) return;
        var feature = e.features[0];
        var coords = (feature.geometry as GeoJSON.Point).coordinates.slice() as [number, number];
        var p = feature.properties as Record<string, any>;
        var name = p.name || "Unknown";
        var city = p.city || ""; var state = p.state || "";
        var location = [city, state].filter(Boolean).join(", ");
        var address = p.address || "";
        var html = "<div style=\"font-family:system-ui,sans-serif;padding:4px;min-width:200px;\">" +
          "<div style=\"font-size:15px;font-weight:700;color:#1B2A4A;margin-bottom:2px;\">" + name + "</div>" +
          "<div style=\"font-size:12px;color:#64748b;margin-bottom:8px;\">" + location + "</div>" +
          "<div style=\"display:flex;gap:8px;margin-bottom:6px;\">" +
            "<span style=\"background:#a0845c;color:white;border-radius:4px;padding:2px 8px;font-size:11px;font-weight:600;\">Brownfield</span>" +
          "</div>" +
          "<div style=\"border-top:1px solid #e2e8f0;padding-top:6px;font-size:12px;color:#334155;\">";
        if (address) html += "<div style=\"margin:3px 0;\">" + address + "</div>";
        html += "</div></div>";
        if (popupRef.current) popupRef.current.remove();
        popupRef.current = new mapboxgl.Popup({ offset: 12, maxWidth: "300px" }).setLngLat(coords).setHTML(html).addTo(map!);
      });
      map.on("mouseenter", BROWNFIELDS_LAYER, function () { map!.getCanvas().style.cursor = "pointer"; });
      map.on("mouseleave", BROWNFIELDS_LAYER, function () { map!.getCanvas().style.cursor = ""; });
    }
    if (mapLoaded.current) setup(); else map.on("load", setup);
  }, [layers.brownfields]);

  useEffect(function () {
    var map = mapRef.current;
    if (!map) return;
    function setup() {
      if (!map) return;
      if (map.getLayer(DATA_CENTERS_LAYER)) {
        map.setLayoutProperty(DATA_CENTERS_LAYER, "visibility", layers.dataCenters ? "visible" : "none");
        return;
      }
      if (!layers.dataCenters) return;
      map.addSource(DATA_CENTERS_SOURCE, { type: "geojson", data: "/data/data-centers.geojson" });
      map.addLayer({
        id: DATA_CENTERS_LAYER, type: "symbol", source: DATA_CENTERS_SOURCE,
        layout: {
          "icon-image": SQUARE_ICON,
          "icon-size": ["interpolate", ["linear"], ["zoom"], 4, 0.35, 8, 0.5, 12, 0.7],
          "icon-allow-overlap": true,
        },
        paint: { "icon-color": "#06b6d4", "icon-opacity": 0.9 },
      });
      map.on("click", DATA_CENTERS_LAYER, function (e) {
        if (!e.features || e.features.length === 0) return;
        var feature = e.features[0];
        var coords = (feature.geometry as GeoJSON.Point).coordinates.slice() as [number, number];
        var p = feature.properties as Record<string, any>;
        var name = p.name || "Data Center"; var operator = p.operator || "";
        var city = p.city || ""; var state = p.state || "";
        var location = [city, state].filter(Boolean).join(", ");
        var address = p.address || ""; var capacity = p.capacity || "";
        var levels = p.building_levels || ""; var website = p.website || "";
        var html = "<div style=\"font-family:system-ui,sans-serif;padding:4px;min-width:220px;\">" +
          "<div style=\"font-size:15px;font-weight:700;color:#1B2A4A;margin-bottom:2px;\">" + name + "</div>" +
          (location ? "<div style=\"font-size:12px;color:#64748b;margin-bottom:8px;\">" + location + "</div>" : "") +
          "<div style=\"display:flex;gap:8px;margin-bottom:6px;\">" +
            "<span style=\"background:#06b6d4;color:white;border-radius:4px;padding:2px 8px;font-size:11px;font-weight:600;\">Data Center</span>" +
            (operator ? "<span style=\"background:#334155;color:white;border-radius:4px;padding:2px 8px;font-size:11px;font-weight:600;\">" + operator + "</span>" : "") +
          "</div>" +
          "<div style=\"border-top:1px solid #e2e8f0;padding-top:6px;font-size:12px;color:#334155;\">";
        if (address) html += "<div style=\"display:flex;justify-content:space-between;margin:3px 0;\"><span>Address</span><strong>" + address + "</strong></div>";
        if (capacity) html += "<div style=\"display:flex;justify-content:space-between;margin:3px 0;\"><span>Capacity</span><strong>" + capacity + "</strong></div>";
        if (levels) html += "<div style=\"display:flex;justify-content:space-between;margin:3px 0;\"><span>Floors</span><strong>" + levels + "</strong></div>";
        if (website) html += "<div style=\"margin:3px 0;\"><a href=\"" + website + "\" target=\"_blank\" rel=\"noopener\" style=\"color:#06b6d4;text-decoration:underline;\">Website</a></div>";
        html += "</div></div>";
        if (popupRef.current) popupRef.current.remove();
        popupRef.current = new mapboxgl.Popup({ offset: 12, maxWidth: "320px" }).setLngLat(coords).setHTML(html).addTo(map!);
      });
      map.on("mouseenter", DATA_CENTERS_LAYER, function () { map!.getCanvas().style.cursor = "pointer"; });
      map.on("mouseleave", DATA_CENTERS_LAYER, function () { map!.getCanvas().style.cursor = ""; });
    }
    if (mapLoaded.current) setup(); else map.on("load", setup);
  }, [layers.dataCenters]);

  useEffect(function () {
    var map = mapRef.current;
    if (!map) return;
    function setup() {
      if (!map) return;
      if (map.getLayer(UTILITY_TERRITORIES_LAYER)) {
        map.setLayoutProperty(UTILITY_TERRITORIES_LAYER, "visibility", layers.utilityTerritories ? "visible" : "none");
        map.setLayoutProperty(UTILITY_TERRITORIES_OUTLINE_LAYER, "visibility", layers.utilityTerritories ? "visible" : "none");
        return;
      }
      if (!layers.utilityTerritories) return;
      map.addSource(UTILITY_TERRITORIES_SOURCE, { type: "geojson", data: "/data/utility-territories.geojson" });
      var beforeLayer: string | undefined;
      if (map.getLayer(BROWNFIELDS_LAYER)) beforeLayer = BROWNFIELDS_LAYER;
      else if (map.getLayer(POWER_PLANTS_LAYER)) beforeLayer = POWER_PLANTS_LAYER;
      else if (map.getLayer(TRANSMISSION_LINES_LAYER)) beforeLayer = TRANSMISSION_LINES_LAYER;
      else if (map.getLayer(SUBSTATIONS_LAYER)) beforeLayer = SUBSTATIONS_LAYER;
      map.addLayer({
        id: UTILITY_TERRITORIES_LAYER, type: "fill", source: UTILITY_TERRITORIES_SOURCE,
        paint: {
          "fill-color": ["match", ["get", "ratio_class"], "surplus", "#22c55e", "balanced", "#f59e0b", "constrained", "#ef4444", "unknown", "#94a3b8", "#94a3b8"],
          "fill-opacity": ["match", ["get", "ratio_class"], "surplus", 0.25, "balanced", 0.25, "constrained", 0.25, "unknown", 0.15, 0.15],
        },
      }, beforeLayer);
      map.addLayer({
        id: UTILITY_TERRITORIES_OUTLINE_LAYER, type: "line", source: UTILITY_TERRITORIES_SOURCE,
        paint: { "line-color": "#94a3b8", "line-opacity": 0.4, "line-width": 0.5 },
      }, beforeLayer);
      map.on("click", UTILITY_TERRITORIES_LAYER, function (e) {
        if (!e.features || e.features.length === 0) return;
        var p = e.features[0].properties as Record<string, any>;
        var name = p.name || "Unknown"; var state = p.state || "";
        var utilType = p.utility_type || "";
        var capacityMw = p.capacity_mw; var avgLoadMw = p.avg_load_mw;
        var ratio = p.ratio; var ratioClass = p.ratio_class || "unknown";
        var ratioColor = ratioClass === "surplus" ? "#22c55e" : ratioClass === "balanced" ? "#f59e0b" : ratioClass === "constrained" ? "#ef4444" : "#94a3b8";
        var ratioLabel = ratioClass === "surplus" ? "Surplus" : ratioClass === "balanced" ? "Balanced" : ratioClass === "constrained" ? "Constrained" : "No Data";
        var metaLine = [utilType, state ? "State: " + state : ""].filter(Boolean).join(" \u00b7 ");
        var html = "<div style=\"font-family:system-ui,sans-serif;padding:4px;min-width:220px;\">" +
          "<div style=\"font-size:15px;font-weight:700;color:#1B2A4A;margin-bottom:2px;\">" + name + "</div>" +
          (metaLine ? "<div style=\"font-size:12px;color:#64748b;margin-bottom:8px;\">" + metaLine + "</div>" : "") +
          "<div style=\"border-top:1px solid #e2e8f0;padding-top:6px;font-size:12px;color:#334155;\">";
        if (capacityMw !== null && capacityMw !== undefined) html += "<div style=\"display:flex;justify-content:space-between;margin:3px 0;\"><span>Capacity</span><strong>" + Number(capacityMw).toLocaleString() + " MW</strong></div>";
        if (avgLoadMw !== null && avgLoadMw !== undefined) html += "<div style=\"display:flex;justify-content:space-between;margin:3px 0;\"><span>Avg Load</span><strong>" + Number(avgLoadMw).toLocaleString() + " MW</strong></div>";
        if (ratio !== null && ratio !== undefined) html += "<div style=\"display:flex;justify-content:space-between;margin:3px 0;\"><span>Ratio</span><strong>" + Number(ratio).toFixed(2) + "</strong></div>";
        html += "<div style=\"display:flex;align-items:center;gap:6px;margin-top:6px;\">" +
          "<span style=\"display:inline-block;width:10px;height:10px;border-radius:50%;background:" + ratioColor + ";\"></span>" +
          "<span style=\"font-weight:600;color:" + ratioColor + ";\">" + ratioLabel + "</span></div>";
        html += "</div></div>";
        if (popupRef.current) popupRef.current.remove();
        popupRef.current = new mapboxgl.Popup({ offset: 12, maxWidth: "320px" }).setLngLat(e.lngLat).setHTML(html).addTo(map!);
      });
      map.on("mouseenter", UTILITY_TERRITORIES_LAYER, function () { map!.getCanvas().style.cursor = "pointer"; });
      map.on("mouseleave", UTILITY_TERRITORIES_LAYER, function () { map!.getCanvas().style.cursor = ""; });
    }
    if (mapLoaded.current) setup(); else map.on("load", setup);
  }, [layers.utilityTerritories]);

  useEffect(function () {
    var map = mapRef.current;
    if (!map) return;
    function setup() {
      if (!map) return;
      if (map.getLayer(LMP_NODES_LAYER)) {
        map.setLayoutProperty(LMP_NODES_LAYER, "visibility", layers.lmpNodes ? "visible" : "none");
        return;
      }
      if (!layers.lmpNodes) return;
      map.addSource(LMP_NODES_SOURCE, { type: "geojson", data: "/data/lmp-nodes.geojson" });
      map.addLayer({
        id: LMP_NODES_LAYER, type: "circle", source: LMP_NODES_SOURCE,
        paint: {
          "circle-color": ["match", ["get", "lmp_class"], "low", "#22c55e", "moderate", "#f59e0b", "high", "#ef4444", "#94a3b8"],
          "circle-radius": ["interpolate", ["linear"], ["zoom"], 4, 4, 8, 7, 12, 10],
          "circle-opacity": 0.85, "circle-stroke-color": "#ffffff", "circle-stroke-width": 1,
        },
      });
      map.on("click", LMP_NODES_LAYER, function (e) {
        if (!e.features || e.features.length === 0) return;
        var feature = e.features[0];
        var coords = (feature.geometry as GeoJSON.Point).coordinates.slice() as [number, number];
        var p = feature.properties as Record<string, any>;
        if (typeof p.avg_lmp === "string") p.avg_lmp = parseFloat(p.avg_lmp);
        if (popupRef.current) popupRef.current.remove();
        popupRef.current = new mapboxgl.Popup({ offset: 12, maxWidth: "300px" }).setLngLat(coords).setHTML(buildLmpPopupHTML(p)).addTo(map!);
      });
      map.on("mouseenter", LMP_NODES_LAYER, function () { map!.getCanvas().style.cursor = "pointer"; });
      map.on("mouseleave", LMP_NODES_LAYER, function () { map!.getCanvas().style.cursor = ""; });
    }
    if (mapLoaded.current) setup(); else map.on("load", setup);
  }, [layers.lmpNodes, buildLmpPopupHTML]);

  // --- Load opportunity sites ---

  useEffect(function () {
    var map = mapRef.current;
    if (!map) return;
    function setup() {
      if (!map) return;
      if (map.getLayer(OPPORTUNITIES_LAYER)) {
        map.setLayoutProperty(OPPORTUNITIES_LAYER, "visibility", layers.opportunities ? "visible" : "none");
        return;
      }
      if (!layers.opportunities) return;
      fetch("/data/opportunities.geojson")
        .then(function (res) { return res.json(); })
        .then(function (geojson) {
          if (!map || map.getSource(OPPORTUNITIES_SOURCE)) return;
          var sites: ScoredSite[] = geojson.features
            .map(function (f: any) { return f.properties as ScoredSite; })
            .sort(function (a: ScoredSite, b: ScoredSite) { return b.composite_score - a.composite_score; });
          onOpportunitySitesLoaded(sites);
          map.addSource(OPPORTUNITIES_SOURCE, { type: "geojson", data: geojson });
          map.addLayer({
            id: OPPORTUNITIES_LAYER, type: "circle", source: OPPORTUNITIES_SOURCE,
            paint: {
              "circle-color": ["match", ["get", "opportunity_type"],
                "retired_plant", "#ef4444", "adaptive_reuse", "#f59e0b", "greenfield", "#22c55e", "#94a3b8"],
              "circle-radius": ["interpolate", ["linear"], ["get", "composite_score"], 50, 4, 70, 6, 85, 9, 95, 12],
              "circle-opacity": 0.9,
              "circle-stroke-color": "#ffffff",
              "circle-stroke-width": 1.5,
            },
          });
          map.on("click", OPPORTUNITIES_LAYER, function (e) {
            if (!e.features || e.features.length === 0) return;
            var p = e.features[0].properties as Record<string, any>;
            var pf = function (v: any) { return parseFloat(v) || 0; };
            var site: ScoredSite = {
              plant_name: p.plant_name, state: p.state,
              latitude: pf(p.latitude), longitude: pf(p.longitude),
              total_capacity_mw: pf(p.total_capacity_mw),
              fuel_type: p.fuel_type, status: p.status,
              planned_retirement_date: p.planned_retirement_date || undefined,
              opportunity_type: p.opportunity_type || undefined,
              qualifying_substation: p.qualifying_substation || undefined,
              qualifying_sub_kv: pf(p.qualifying_sub_kv) || undefined,
              composite_score: pf(p.composite_score),
              time_to_power: pf(p.time_to_power), site_readiness: pf(p.site_readiness),
              connectivity: pf(p.connectivity), risk_factors: pf(p.risk_factors),
              sub_distance_score: pf(p.sub_distance_score), sub_voltage_score: pf(p.sub_voltage_score),
              gen_capacity_score: pf(p.gen_capacity_score), tx_lines_score: pf(p.tx_lines_score),
              queue_withdrawal_score: pf(p.queue_withdrawal_score),
              fuel_type_score: pf(p.fuel_type_score), capacity_scale_score: pf(p.capacity_scale_score),
              longitude_score: pf(p.longitude_score), latitude_score: pf(p.latitude_score),
              broadband_score: pf(p.broadband_score),
              contamination_score: pf(p.contamination_score), operational_status_score: pf(p.operational_status_score),
              flood_zone_score: pf(p.flood_zone_score),
              lmp_score: pf(p.lmp_score), nearest_lmp_avg: pf(p.nearest_lmp_avg),
              nearest_lmp_node: p.nearest_lmp_node || "",
              nearest_sub_name: p.nearest_sub_name,
              nearest_sub_distance_miles: pf(p.nearest_sub_distance_miles),
              nearest_sub_voltage_kv: pf(p.nearest_sub_voltage_kv),
              nearest_sub_lines: pf(p.nearest_sub_lines),
              queue_count_20mi: pf(p.queue_count_20mi),
              queue_mw_20mi: pf(p.queue_mw_20mi),
            };
            if (popupRef.current) popupRef.current.remove();
            var coords = (e.features[0].geometry as GeoJSON.Point).coordinates.slice() as [number, number];
            popupRef.current = new mapboxgl.Popup({ offset: 14, maxWidth: "340px" }).setLngLat(coords).setHTML(buildOpportunityPopupHTML(site)).addTo(map!);
          });
          map.on("mouseenter", OPPORTUNITIES_LAYER, function () { map!.getCanvas().style.cursor = "pointer"; });
          map.on("mouseleave", OPPORTUNITIES_LAYER, function () { map!.getCanvas().style.cursor = ""; });
        })
        .catch(function () { /* opportunities.geojson may not exist yet */ });
    }
    if (mapLoaded.current) setup(); else map.on("load", setup);
  }, [layers.opportunities, buildOpportunityPopupHTML, onOpportunitySitesLoaded]);

  // --- Load scored sites ---

  useEffect(function () {
    var map = mapRef.current;
    if (!map) return;
    function setupScoredLayer() {
      if (!map) return;
      if (map.getSource(SCORED_SITES_SOURCE)) return;
      fetch("/data/scored-sites.geojson")
        .then(function (res) { return res.json(); })
        .then(function (geojson) {
          var sites: ScoredSite[] = geojson.features
            .map(function (f: any) { return f.properties as ScoredSite; })
            .sort(function (a: ScoredSite, b: ScoredSite) { return b.composite_score - a.composite_score; });
          onScoredSitesLoaded(sites);
          if (!map || map.getSource(SCORED_SITES_SOURCE)) return;
          map.addSource(SCORED_SITES_SOURCE, { type: "geojson", data: geojson });
          map.addLayer({
            id: SCORED_SITES_LAYER, type: "symbol", source: SCORED_SITES_SOURCE,
            layout: {
              "icon-image": STAR_ICON,
              "icon-size": ["interpolate", ["linear"], ["get", "composite_score"], 50, 0.5, 70, 0.7, 85, 0.9, 95, 1.1],
              "icon-allow-overlap": true,
            },
            paint: {
              "icon-color": ["interpolate", ["linear"], ["get", "composite_score"], 50, "#a16207", 70, "#ca8a04", 85, "#eab308", 95, "#facc15"],
              "icon-opacity": 0.95, "icon-halo-color": "#000000", "icon-halo-width": 0.5,
            },
          });
          map.on("click", SCORED_SITES_LAYER, function (e) {
            if (!e.features || e.features.length === 0) return;
            var p = e.features[0].properties as Record<string, any>;
            var pf = function (v: any) { return parseFloat(v) || 0; };
            var site: ScoredSite = {
              plant_name: p.plant_name, state: p.state,
              latitude: pf(p.latitude), longitude: pf(p.longitude),
              total_capacity_mw: pf(p.total_capacity_mw),
              fuel_type: p.fuel_type, status: p.status,
              planned_retirement_date: p.planned_retirement_date || undefined,
              composite_score: pf(p.composite_score),
              time_to_power: pf(p.time_to_power), site_readiness: pf(p.site_readiness),
              connectivity: pf(p.connectivity), risk_factors: pf(p.risk_factors),
              sub_distance_score: pf(p.sub_distance_score), sub_voltage_score: pf(p.sub_voltage_score),
              gen_capacity_score: pf(p.gen_capacity_score), tx_lines_score: pf(p.tx_lines_score),
              queue_withdrawal_score: pf(p.queue_withdrawal_score),
              fuel_type_score: pf(p.fuel_type_score), capacity_scale_score: pf(p.capacity_scale_score),
              longitude_score: pf(p.longitude_score), latitude_score: pf(p.latitude_score),
              broadband_score: pf(p.broadband_score),
              contamination_score: pf(p.contamination_score), operational_status_score: pf(p.operational_status_score),
              flood_zone_score: pf(p.flood_zone_score),
              lmp_score: pf(p.lmp_score), nearest_lmp_avg: pf(p.nearest_lmp_avg),
              nearest_lmp_node: p.nearest_lmp_node || "",
              nearest_sub_name: p.nearest_sub_name,
              nearest_sub_distance_miles: pf(p.nearest_sub_distance_miles),
              nearest_sub_voltage_kv: pf(p.nearest_sub_voltage_kv),
              nearest_sub_lines: pf(p.nearest_sub_lines),
              queue_count_20mi: pf(p.queue_count_20mi),
              queue_mw_20mi: pf(p.queue_mw_20mi),
            };
            if (popupRef.current) popupRef.current.remove();
            var coords = (e.features[0].geometry as GeoJSON.Point).coordinates.slice() as [number, number];
            popupRef.current = new mapboxgl.Popup({ offset: 14, maxWidth: "340px" }).setLngLat(coords).setHTML(buildScoredSitePopupHTML(site)).addTo(map!);
            runProximityAnalysis(site, proximityRadius);
          });
          map.on("mouseenter", SCORED_SITES_LAYER, function () { map!.getCanvas().style.cursor = "pointer"; });
          map.on("mouseleave", SCORED_SITES_LAYER, function () { map!.getCanvas().style.cursor = ""; });
        });
    }
    if (mapLoaded.current) setupScoredLayer(); else map.on("load", setupScoredLayer);
  }, [buildScoredSitePopupHTML, runProximityAnalysis, proximityRadius, onScoredSitesLoaded]);

  // --- Filter effects ---

  useEffect(function () {
    var map = mapRef.current;
    if (!map || !map.getLayer(SCORED_SITES_LAYER)) return;
    var conditions: any[] = ["all"];
    conditions.push([">=", ["get", "total_capacity_mw"], minMW]);
    if (selectedState) conditions.push(["==", ["get", "state"], selectedState]);
    map.setFilter(SCORED_SITES_LAYER, conditions);
  }, [minMW, selectedState]);

  useEffect(function () {
    var map = mapRef.current;
    if (!map || !map.getLayer(POWER_PLANTS_LAYER)) return;
    var conditions: any[] = ["all"];
    conditions.push([">=", ["get", "total_capacity_mw"], minMW]);
    if (selectedState) conditions.push(["==", ["get", "state"], selectedState]);
    map.setFilter(POWER_PLANTS_LAYER, conditions);
  }, [minMW, selectedState]);

  // --- Re-run proximity on radius change ---

  useEffect(function () {
    if (!proximityResult) return;
    var site = proximityResult.site;
    var timeout = setTimeout(function () { runProximityAnalysis(site, proximityRadius); }, 300);
    return function () { clearTimeout(timeout); };
  }, [proximityRadius]); // eslint-disable-line react-hooks/exhaustive-deps

  // --- Render ---

  return (
    <div className="flex-1 h-full relative">
      <div ref={mapContainer} className="w-full h-full" />

      {/* Proximity Analysis Panel */}
      {proximityResult && (
        <div className="absolute top-4 left-4 z-20 w-80 bg-[#1B2A4A]/95 backdrop-blur-sm border border-white/10 rounded-lg text-white shadow-xl">
          <div className="px-4 pt-3 pb-2 border-b border-white/10">
            <div className="flex items-start justify-between">
              <div>
                <div className="text-sm font-semibold truncate pr-2">{proximityResult.site.plant_name}</div>
                <div className="text-[11px] text-slate-400">Proximity Analysis</div>
              </div>
              <button onClick={clearProximityAnalysis} className="text-slate-400 hover:text-white text-lg leading-none shrink-0 mt-0.5">&times;</button>
            </div>
          </div>
          <div className="px-4 py-2.5 border-b border-white/10">
            <label className="block text-xs text-slate-400 mb-1.5">
              Radius: <span className="text-white font-medium">{proximityRadius} miles</span>
            </label>
            <input type="range" min={5} max={20} step={5} value={proximityRadius}
              onChange={function (e) { setProximityRadius(Number(e.target.value)); }}
              className="w-full accent-yellow-500" />
            <div className="flex justify-between text-[10px] text-slate-500 mt-0.5">
              <span>5 mi</span><span>10</span><span>15</span><span>20 mi</span>
            </div>
          </div>
          <div className="px-4 py-3 space-y-3 max-h-[60vh] overflow-y-auto">
            {proximityLoading ? (
              <div className="text-xs text-slate-400 text-center py-2">Analyzing...</div>
            ) : (
              <>
                <div>
                  <div className="text-xs font-semibold text-slate-300 mb-1.5">Substations ({proximityResult.substations.total})</div>
                  <div className="space-y-1 text-xs">
                    <div className="flex items-center justify-between text-slate-300">
                      <span className="flex items-center gap-1.5"><span className="inline-block w-2 h-2 rotate-45 bg-[#a78bfa]"></span>500+ kV</span>
                      <span className="font-medium">{proximityResult.substations.by500Plus}</span>
                    </div>
                    <div className="flex items-center justify-between text-slate-300">
                      <span className="flex items-center gap-1.5"><span className="inline-block w-2 h-2 rotate-45 bg-[#818cf8]"></span>345-499 kV</span>
                      <span className="font-medium">{proximityResult.substations.by345to499}</span>
                    </div>
                    <div className="flex items-center justify-between text-slate-300">
                      <span className="flex items-center gap-1.5"><span className="inline-block w-2 h-2 rotate-45 bg-[#38bdf8]"></span>230-344 kV</span>
                      <span className="font-medium">{proximityResult.substations.by230to344}</span>
                    </div>
                    <div className="flex items-center justify-between text-slate-300">
                      <span className="flex items-center gap-1.5"><span className="inline-block w-2 h-2 rotate-45 bg-[#22d3ee]"></span>Under 230 kV</span>
                      <span className="font-medium">{proximityResult.substations.byUnder230}</span>
                    </div>
                  </div>
                </div>
                <div>
                  <div className="text-xs font-semibold text-slate-300 mb-1.5">Transmission Crossings ({proximityResult.transmissionLines.total})</div>
                  <div className="space-y-1 text-xs">
                    <div className="flex items-center justify-between text-slate-300">
                      <span className="flex items-center gap-1.5"><span className="inline-block w-3 h-[3px] bg-[#a78bfa] rounded"></span>500+ kV</span>
                      <span className="font-medium">{proximityResult.transmissionLines.by500Plus}</span>
                    </div>
                    <div className="flex items-center justify-between text-slate-300">
                      <span className="flex items-center gap-1.5"><span className="inline-block w-3 h-[2px] bg-[#818cf8] rounded"></span>345-499 kV</span>
                      <span className="font-medium">{proximityResult.transmissionLines.by345to499}</span>
                    </div>
                    <div className="flex items-center justify-between text-slate-300">
                      <span className="flex items-center gap-1.5"><span className="inline-block w-3 h-[2px] bg-[#38bdf8] rounded"></span>230-344 kV</span>
                      <span className="font-medium">{proximityResult.transmissionLines.by230to344}</span>
                    </div>
                    <div className="flex items-center justify-between text-slate-300">
                      <span className="flex items-center gap-1.5"><span className="inline-block w-3 h-[1px] bg-[#22d3ee] rounded"></span>Under 230 kV</span>
                      <span className="font-medium">{proximityResult.transmissionLines.byUnder230}</span>
                    </div>
                  </div>
                </div>
                <div>
                  <div className="text-xs font-semibold text-slate-300 mb-1.5">Queue Withdrawals ({proximityResult.queueWithdrawals.total})</div>
                  <div className="space-y-1 text-xs">
                    <div className="flex items-center justify-between text-slate-300">
                      <span className="flex items-center gap-1.5"><span className="text-orange-500 text-[10px] leading-none">&#9650;</span>Total Projects</span>
                      <span className="font-medium">{proximityResult.queueWithdrawals.total}</span>
                    </div>
                    <div className="flex items-center justify-between text-orange-400">
                      <span className="flex items-center gap-1.5"><span className="text-[10px] leading-none">&#9889;</span>Withdrawn MW</span>
                      <span className="font-medium">{Math.round(proximityResult.queueWithdrawals.totalWithdrawnMW).toLocaleString()} MW</span>
                    </div>
                  </div>
                </div>
              </>
            )}
          </div>
        </div>
      )}

      {/* Legend */}
      <div className="absolute bottom-6 right-2 z-10">
        {legendOpen ? (
          <div className="bg-[#1B2A4A]/90 backdrop-blur-sm border border-white/10 rounded-lg px-3 py-2.5 text-xs text-slate-200 min-w-[180px]">
            <button onClick={() => setLegendOpen(false)} className="w-full flex items-center justify-between mb-2">
              <span className="font-semibold text-[11px] uppercase tracking-wider text-slate-300">Legend</span>
              <span className="text-slate-400 hover:text-white text-sm leading-none">&times;</span>
            </button>
            <div className="space-y-1.5">
              <div className="flex items-center gap-2"><span className="text-yellow-400 text-sm leading-none">&#9733;</span><span>Scored Site</span></div>
              <div className="flex items-center gap-2"><span className="inline-block w-2.5 h-2.5 rounded-full bg-[#22c55e]"></span><span>Operating Plant</span></div>
              <div className="flex items-center gap-2"><span className="inline-block w-2.5 h-2.5 rounded-full bg-[#f97316]"></span><span>Retiring Plant</span></div>
              <div className="flex items-center gap-2"><span className="inline-block w-2.5 h-2.5 rounded-full bg-[#ef4444]"></span><span>Retired Plant</span></div>
              <div className="flex items-center gap-2"><span className="text-orange-500 text-[10px] leading-none">&#9650;</span><span>Queue Withdrawal</span></div>
              <div className="flex items-center gap-2"><span className="inline-block w-2.5 h-2.5 rounded-sm bg-[#6baed6] opacity-60"></span><span>FEMA Flood Zone</span></div>
              <div className="flex items-center gap-2"><span className="inline-block w-2.5 h-2.5 rounded-sm bg-[#2ca02c] opacity-60"></span><span>Broadband Coverage</span></div>
              <div className="flex items-center gap-2"><span className="inline-block w-2.5 h-2.5 rounded-full bg-[#a0845c]"></span><span>Brownfield Site</span></div>
              <div className="flex items-center gap-2"><span className="inline-block w-2.5 h-2.5 rounded-sm bg-[#06b6d4]"></span><span>Data Center</span></div>
              <div className="border-t border-white/10 my-1.5"></div>
              <div className="flex items-center gap-2"><span className="inline-block w-2.5 h-2.5 rounded-sm bg-[#22c55e] opacity-60"></span><span>Surplus Territory (&gt;1.5x)</span></div>
              <div className="flex items-center gap-2"><span className="inline-block w-2.5 h-2.5 rounded-sm bg-[#f59e0b] opacity-60"></span><span>Balanced Territory</span></div>
              <div className="flex items-center gap-2"><span className="inline-block w-2.5 h-2.5 rounded-sm bg-[#ef4444] opacity-60"></span><span>Constrained Territory</span></div>
              <div className="border-t border-white/10 my-1.5"></div>
              <div className="flex items-center gap-2"><span className="inline-block w-2.5 h-2.5 rotate-45 bg-[#22d3ee]"></span><span>138-229 kV Sub</span></div>
              <div className="flex items-center gap-2"><span className="inline-block w-2.5 h-2.5 rotate-45 bg-[#38bdf8]"></span><span>230-344 kV Sub</span></div>
              <div className="flex items-center gap-2"><span className="inline-block w-2.5 h-2.5 rotate-45 bg-[#818cf8]"></span><span>345 kV+ Sub</span></div>
              <div className="border-t border-white/10 my-1.5"></div>
              <div className="flex items-center gap-2"><span className="inline-block w-2.5 h-2.5 rounded-full bg-[#ef4444] border border-white/60"></span><span>Retired Plant Opp.</span></div>
              <div className="flex items-center gap-2"><span className="inline-block w-2.5 h-2.5 rounded-full bg-[#f59e0b] border border-white/60"></span><span>Adaptive Reuse Opp.</span></div>
              <div className="flex items-center gap-2"><span className="inline-block w-2.5 h-2.5 rounded-full bg-[#22c55e] border border-white/60"></span><span>Greenfield Opp.</span></div>
              <div className="border-t border-white/10 my-1.5"></div>
              <div className="flex items-center gap-2"><span className="inline-block w-2.5 h-2.5 rounded-full bg-[#22c55e] border border-white/40"></span><span>LMP Low (Headroom)</span></div>
              <div className="flex items-center gap-2"><span className="inline-block w-2.5 h-2.5 rounded-full bg-[#f59e0b] border border-white/40"></span><span>LMP Moderate</span></div>
              <div className="flex items-center gap-2"><span className="inline-block w-2.5 h-2.5 rounded-full bg-[#ef4444] border border-white/40"></span><span>LMP High (Congestion)</span></div>
              <div className="border-t border-white/10 my-1.5"></div>
              <div className="flex items-center gap-2"><span className="inline-block w-4 h-[1px] bg-[#22d3ee] rounded"></span><span>138-229 kV Line</span></div>
              <div className="flex items-center gap-2"><span className="inline-block w-4 h-[2px] bg-[#38bdf8] rounded"></span><span>230-344 kV Line</span></div>
              <div className="flex items-center gap-2"><span className="inline-block w-4 h-[3px] bg-[#818cf8] rounded"></span><span>345-499 kV Line</span></div>
              <div className="flex items-center gap-2"><span className="inline-block w-4 h-[4px] bg-[#a78bfa] rounded"></span><span>500 kV+ Line</span></div>
            </div>
          </div>
        ) : (
          <button onClick={() => setLegendOpen(true)}
            className="bg-[#1B2A4A]/90 backdrop-blur-sm border border-white/10 rounded-lg px-3 py-2 text-[11px] font-semibold uppercase tracking-wider text-slate-300 hover:text-white">
            Legend
          </button>
        )}
      </div>
    </div>
  );
});

export default MapComponent;
