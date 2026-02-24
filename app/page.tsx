"use client";

import { useEffect, useRef, useState, useCallback, useMemo } from "react";
import mapboxgl from "mapbox-gl";
import "mapbox-gl/dist/mapbox-gl.css";

var MAPBOX_TOKEN = process.env.NEXT_PUBLIC_MAPBOX_TOKEN || "";

var US_STATES = [
  "AL","AK","AZ","AR","CA","CO","CT","DE","FL","GA",
  "HI","ID","IL","IN","IA","KS","KY","LA","ME","MD",
  "MA","MI","MN","MS","MO","MT","NE","NV","NH","NJ",
  "NM","NY","NC","ND","OH","OK","OR","PA","RI","SC",
  "SD","TN","TX","UT","VT","VA","WA","WV","WI","WY",
];

var POWER_PLANTS_SOURCE = "power-plants";
var POWER_PLANTS_LAYER = "power-plants-circles";
var SUBSTATIONS_SOURCE = "substations";
var SUBSTATIONS_LAYER = "substations-diamonds";
var TRANSMISSION_LINES_SOURCE = "transmission-lines";
var TRANSMISSION_LINES_LAYER = "transmission-lines-lines";
var QUEUE_WITHDRAWALS_SOURCE = "queue-withdrawals";
var QUEUE_WITHDRAWALS_LAYER = "queue-withdrawals-triangles";
var SCORED_SITES_SOURCE = "scored-sites";
var SCORED_SITES_LAYER = "scored-sites-stars";
var DIAMOND_ICON = "diamond-icon";
var STAR_ICON = "star-icon";
var TRIANGLE_ICON = "triangle-icon";

interface ScoredSite {
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

export default function Home() {
  var mapContainer = useRef<HTMLDivElement>(null);
  var mapRef = useRef<mapboxgl.Map | null>(null);
  var mapLoaded = useRef(false);
  var popupRef = useRef<mapboxgl.Popup | null>(null);

  var [layersOpen, setLayersOpen] = useState(true);
  var [filtersOpen, setFiltersOpen] = useState(true);
  var [resultsOpen, setResultsOpen] = useState(true);
  var [minMW, setMinMW] = useState(50);
  var [selectedState, setSelectedState] = useState("");
  var [layers, setLayers] = useState({
    powerPlants: false,
    substations: false,
    transmissionLines: false,
    queueWithdrawals: false,
  });
  var [scoredSites, setScoredSites] = useState<ScoredSite[]>([]);
  var [legendOpen, setLegendOpen] = useState(true);

  var filteredSites = useMemo(function () {
    return scoredSites.filter(function (site) {
      if (site.total_capacity_mw < minMW) return false;
      if (selectedState && site.state !== selectedState) return false;
      return true;
    });
  }, [scoredSites, minMW, selectedState]);

  function toggleLayer(key: keyof typeof layers) {
    setLayers(function (prev) {
      return { ...prev, [key]: !prev[key] };
    });
  }

  // Build popup HTML for a power plant feature
  var buildPopupHTML = useCallback(function (props: Record<string, any>): string {
    var statusColors: Record<string, string> = {
      operating: "#22c55e",
      retiring: "#f97316",
      retired: "#ef4444",
    };
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

  // Build popup HTML for a substation feature
  var buildSubstationPopupHTML = useCallback(function (props: Record<string, any>): string {
    var name = props.NAME || "Unknown";
    var city = props.CITY || "";
    var state = props.STATE || "";
    var location = [city, state].filter(Boolean).join(", ");
    var maxVolt = props.MAX_VOLT != null ? Number(props.MAX_VOLT) : null;
    var minVolt = props.MIN_VOLT != null ? Number(props.MIN_VOLT) : null;
    var status = props.STATUS || "Unknown";
    var type = props.TYPE || "";
    var lines = props.LINES != null ? Number(props.LINES) : null;

    var voltColor = "#22d3ee";
    if (maxVolt != null && maxVolt >= 345) voltColor = "#a78bfa";
    else if (maxVolt != null && maxVolt >= 230) voltColor = "#38bdf8";

    var html = "<div style=\"font-family:system-ui,sans-serif;padding:4px;min-width:220px;\">" +
      "<div style=\"font-size:15px;font-weight:700;color:#1B2A4A;margin-bottom:2px;\">" + name + "</div>" +
      "<div style=\"font-size:12px;color:#64748b;margin-bottom:8px;\">" + location + "</div>" +
      "<div style=\"display:flex;gap:8px;margin-bottom:6px;\">" +
        "<span style=\"background:" + voltColor + ";color:#0f172a;border-radius:4px;padding:2px 8px;font-size:11px;font-weight:600;\">" +
          (maxVolt != null ? maxVolt + " kV" : "N/A") + "</span>" +
        (type ? "<span style=\"background:#334155;color:white;border-radius:4px;padding:2px 8px;font-size:11px;font-weight:600;\">" + type + "</span>" : "") +
      "</div>" +
      "<div style=\"border-top:1px solid #e2e8f0;padding-top:6px;font-size:12px;color:#334155;\">" +
        "<div style=\"display:flex;justify-content:space-between;margin:3px 0;\"><span>Status</span><strong>" + status + "</strong></div>";

    if (maxVolt != null) {
      html += "<div style=\"display:flex;justify-content:space-between;margin:3px 0;\"><span>Max Voltage</span><strong>" + maxVolt + " kV</strong></div>";
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

  // Build popup HTML for a transmission line feature
  var buildTransmissionLinePopupHTML = useCallback(function (props: Record<string, any>): string {
    var voltage = props.VOLTAGE != null ? Number(props.VOLTAGE) : null;
    var voltClass = props.VOLT_CLASS || "";
    var owner = props.OWNER || "Unknown";
    var status = props.STATUS || "Unknown";
    var type = props.TYPE || "";
    var sub1 = props.SUB_1 || "";
    var sub2 = props.SUB_2 || "";

    var voltColor = "#22d3ee";
    if (voltage != null && voltage >= 500) voltColor = "#a78bfa";
    else if (voltage != null && voltage >= 345) voltColor = "#818cf8";
    else if (voltage != null && voltage >= 230) voltColor = "#38bdf8";

    var html = "<div style=\"font-family:system-ui,sans-serif;padding:4px;min-width:220px;\">" +
      "<div style=\"font-size:15px;font-weight:700;color:#1B2A4A;margin-bottom:2px;\">Transmission Line</div>" +
      "<div style=\"display:flex;gap:8px;margin-bottom:6px;\">" +
        "<span style=\"background:" + voltColor + ";color:#0f172a;border-radius:4px;padding:2px 8px;font-size:11px;font-weight:600;\">" +
          (voltage != null ? voltage + " kV" : voltClass) + "</span>" +
        (type ? "<span style=\"background:#334155;color:white;border-radius:4px;padding:2px 8px;font-size:11px;font-weight:600;\">" + type + "</span>" : "") +
      "</div>" +
      "<div style=\"border-top:1px solid #e2e8f0;padding-top:6px;font-size:12px;color:#334155;\">" +
        "<div style=\"display:flex;justify-content:space-between;margin:3px 0;\"><span>Owner</span><strong>" + owner + "</strong></div>" +
        "<div style=\"display:flex;justify-content:space-between;margin:3px 0;\"><span>Status</span><strong>" + status + "</strong></div>";

    if (sub1 || sub2) {
      var route = [sub1, sub2].filter(Boolean).join(" → ");
      html += "<div style=\"display:flex;justify-content:space-between;margin:3px 0;\"><span>Route</span><strong>" + route + "</strong></div>";
    }

    html += "</div></div>";
    return html;
  }, []);

  // Build popup HTML for a queue withdrawal feature
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

  // Build popup HTML for a scored site feature
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

    return "<div style=\"font-family:system-ui,sans-serif;padding:4px;min-width:260px;\">" +
      "<div style=\"display:flex;justify-content:space-between;align-items:start;margin-bottom:4px;\">" +
        "<div>" +
          "<div style=\"font-size:15px;font-weight:700;color:#1B2A4A;\">" + s.plant_name + "</div>" +
          "<div style=\"font-size:12px;color:#64748b;\">" + s.state + " &middot; " + s.total_capacity_mw.toLocaleString() + " MW</div>" +
        "</div>" +
        "<div style=\"background:#eab308;color:#0f172a;border-radius:6px;padding:4px 10px;font-size:18px;font-weight:bold;min-width:44px;text-align:center;\">" + s.composite_score + "</div>" +
      "</div>" +
      "<div style=\"font-size:11px;color:#64748b;margin-bottom:6px;\">" + s.fuel_type + " &middot; " + s.status + "</div>" +
      "<div style=\"border-top:1px solid #e2e8f0;padding-top:6px;\">" +
        bar("Power Access", s.power_access, "30%") +
        bar("Grid Capacity", s.grid_capacity, "20%") +
        bar("Site Characteristics", s.site_characteristics, "20%") +
        bar("Connectivity", s.connectivity, "15%") +
        bar("Risk Factors", s.risk_factors, "15%") +
      "</div>" +
      "<div style=\"border-top:1px solid #e2e8f0;margin-top:6px;padding-top:6px;font-size:11px;color:#64748b;\">" +
        "<div style=\"display:flex;justify-content:space-between;margin:2px 0;\"><span>Nearest 345kV+ Sub</span><strong style=\"color:#334155;\">" + s.nearest_sub_name + "</strong></div>" +
        "<div style=\"display:flex;justify-content:space-between;margin:2px 0;\"><span>Distance</span><strong style=\"color:#334155;\">" + s.nearest_sub_distance_miles + " mi</strong></div>" +
        "<div style=\"display:flex;justify-content:space-between;margin:2px 0;\"><span>Sub Voltage</span><strong style=\"color:#334155;\">" + s.nearest_sub_voltage_kv + " kV</strong></div>" +
      "</div></div>";
  }, []);

  // Fly to a scored site and show its popup
  var flyToSite = useCallback(function (site: ScoredSite) {
    var map = mapRef.current;
    if (!map) return;

    map.flyTo({
      center: [site.longitude, site.latitude],
      zoom: 10,
      duration: 1500,
    });

    if (popupRef.current) popupRef.current.remove();

    // Open popup after fly animation
    map.once("moveend", function () {
      if (!mapRef.current) return;
      popupRef.current = new mapboxgl.Popup({ offset: 14, maxWidth: "340px" })
        .setLngLat([site.longitude, site.latitude])
        .setHTML(buildScoredSitePopupHTML(site))
        .addTo(mapRef.current);
    });
  }, [buildScoredSitePopupHTML]);

  // Initialize map
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
      // Create diamond icon for substations layer
      var size = 20;
      var canvas = document.createElement("canvas");
      canvas.width = size;
      canvas.height = size;
      var ctx = canvas.getContext("2d");
      if (ctx) {
        ctx.beginPath();
        ctx.moveTo(size / 2, 1);
        ctx.lineTo(size - 1, size / 2);
        ctx.lineTo(size / 2, size - 1);
        ctx.lineTo(1, size / 2);
        ctx.closePath();
        ctx.fillStyle = "#ffffff";
        ctx.fill();
        var imageData = ctx.getImageData(0, 0, size, size);
        map.addImage(DIAMOND_ICON, imageData, { sdf: true });
      }

      // Create star icon for scored sites layer
      var starSize = 24;
      var starCanvas = document.createElement("canvas");
      starCanvas.width = starSize;
      starCanvas.height = starSize;
      var starCtx = starCanvas.getContext("2d");
      if (starCtx) {
        var cx = starSize / 2;
        var cy = starSize / 2;
        var outerR = starSize / 2 - 1;
        var innerR = outerR * 0.4;
        starCtx.beginPath();
        for (var i = 0; i < 10; i++) {
          var r = i % 2 === 0 ? outerR : innerR;
          var angle = (Math.PI / 2 * -1) + (Math.PI / 5) * i;
          var px = cx + r * Math.cos(angle);
          var py = cy + r * Math.sin(angle);
          if (i === 0) starCtx.moveTo(px, py);
          else starCtx.lineTo(px, py);
        }
        starCtx.closePath();
        starCtx.fillStyle = "#ffffff";
        starCtx.fill();
        var starImageData = starCtx.getImageData(0, 0, starSize, starSize);
        map.addImage(STAR_ICON, starImageData, { sdf: true });
      }

      // Create triangle icon for queue withdrawals layer
      var triSize = 18;
      var triCanvas = document.createElement("canvas");
      triCanvas.width = triSize;
      triCanvas.height = triSize;
      var triCtx = triCanvas.getContext("2d");
      if (triCtx) {
        triCtx.beginPath();
        triCtx.moveTo(triSize / 2, 1);
        triCtx.lineTo(triSize - 1, triSize - 1);
        triCtx.lineTo(1, triSize - 1);
        triCtx.closePath();
        triCtx.fillStyle = "#ffffff";
        triCtx.fill();
        var triImageData = triCtx.getImageData(0, 0, triSize, triSize);
        map.addImage(TRIANGLE_ICON, triImageData, { sdf: true });
      }

      mapLoaded.current = true;
    });

    mapRef.current = map;

    return function () {
      mapLoaded.current = false;
      mapRef.current = null;
      map.remove();
    };
  }, []);

  // Toggle power plants layer based on checkbox
  useEffect(function () {
    var map = mapRef.current;
    if (!map) return;

    function setupLayer() {
      if (!map) return;

      // If layer already exists, just toggle visibility
      if (map.getLayer(POWER_PLANTS_LAYER)) {
        map.setLayoutProperty(
          POWER_PLANTS_LAYER,
          "visibility",
          layers.powerPlants ? "visible" : "none"
        );
        return;
      }

      // Only add source+layer when toggling on for the first time
      if (!layers.powerPlants) return;

      map.addSource(POWER_PLANTS_SOURCE, {
        type: "geojson",
        data: "/data/power-plants.geojson",
      });

      map.addLayer({
        id: POWER_PLANTS_LAYER,
        type: "circle",
        source: POWER_PLANTS_SOURCE,
        paint: {
          "circle-color": [
            "match",
            ["get", "status"],
            "operating", "#22c55e",
            "retiring", "#f97316",
            "retired", "#ef4444",
            "#94a3b8",
          ],
          "circle-radius": [
            "interpolate", ["linear"], ["get", "total_capacity_mw"],
            50, 3,
            500, 7,
            2000, 12,
            5000, 18,
          ],
          "circle-opacity": 0.85,
          "circle-stroke-color": "#ffffff",
          "circle-stroke-width": 0.5,
        },
      });

      // Click handler for popups
      map.on("click", POWER_PLANTS_LAYER, function (e) {
        if (!e.features || e.features.length === 0) return;
        var feature = e.features[0];
        var coords = (feature.geometry as GeoJSON.Point).coordinates.slice() as [number, number];
        var props = feature.properties as Record<string, any>;

        // Parse stringified values from Mapbox
        if (typeof props.total_capacity_mw === "string") {
          props.total_capacity_mw = parseFloat(props.total_capacity_mw);
        }

        // Close existing popup
        if (popupRef.current) {
          popupRef.current.remove();
        }

        popupRef.current = new mapboxgl.Popup({ offset: 12, maxWidth: "300px" })
          .setLngLat(coords)
          .setHTML(buildPopupHTML(props))
          .addTo(map!);
      });

      // Pointer cursor on hover
      map.on("mouseenter", POWER_PLANTS_LAYER, function () {
        map!.getCanvas().style.cursor = "pointer";
      });
      map.on("mouseleave", POWER_PLANTS_LAYER, function () {
        map!.getCanvas().style.cursor = "";
      });
    }

    if (mapLoaded.current) {
      setupLayer();
    } else {
      map.on("load", setupLayer);
    }
  }, [layers.powerPlants, buildPopupHTML]);

  // Toggle substations layer based on checkbox
  useEffect(function () {
    var map = mapRef.current;
    if (!map) return;

    function setupLayer() {
      if (!map) return;

      if (map.getLayer(SUBSTATIONS_LAYER)) {
        map.setLayoutProperty(
          SUBSTATIONS_LAYER,
          "visibility",
          layers.substations ? "visible" : "none"
        );
        return;
      }

      if (!layers.substations) return;

      map.addSource(SUBSTATIONS_SOURCE, {
        type: "geojson",
        data: "/data/substations.geojson",
      });

      map.addLayer({
        id: SUBSTATIONS_LAYER,
        type: "symbol",
        source: SUBSTATIONS_SOURCE,
        layout: {
          "icon-image": DIAMOND_ICON,
          "icon-size": [
            "step", ["get", "MAX_VOLT"],
            0.4,   // default < 230 kV
            230, 0.55,
            345, 0.7,
            500, 0.9,
          ],
          "icon-allow-overlap": true,
        },
        paint: {
          "icon-color": [
            "step", ["get", "MAX_VOLT"],
            "#22d3ee",  // cyan < 230 kV
            230, "#38bdf8",  // light blue
            345, "#818cf8",  // indigo
            500, "#a78bfa",  // purple
          ],
          "icon-opacity": 0.9,
        },
      });

      map.on("click", SUBSTATIONS_LAYER, function (e) {
        if (!e.features || e.features.length === 0) return;
        var feature = e.features[0];
        var coords = (feature.geometry as GeoJSON.Point).coordinates.slice() as [number, number];
        var props = feature.properties as Record<string, any>;

        if (typeof props.MAX_VOLT === "string") props.MAX_VOLT = parseFloat(props.MAX_VOLT);
        if (typeof props.MIN_VOLT === "string") props.MIN_VOLT = parseFloat(props.MIN_VOLT);
        if (typeof props.LINES === "string") props.LINES = parseFloat(props.LINES);

        if (popupRef.current) popupRef.current.remove();

        popupRef.current = new mapboxgl.Popup({ offset: 12, maxWidth: "300px" })
          .setLngLat(coords)
          .setHTML(buildSubstationPopupHTML(props))
          .addTo(map!);
      });

      map.on("mouseenter", SUBSTATIONS_LAYER, function () {
        map!.getCanvas().style.cursor = "pointer";
      });
      map.on("mouseleave", SUBSTATIONS_LAYER, function () {
        map!.getCanvas().style.cursor = "";
      });
    }

    if (mapLoaded.current) {
      setupLayer();
    } else {
      map.on("load", setupLayer);
    }
  }, [layers.substations, buildSubstationPopupHTML]);

  // Toggle transmission lines layer based on checkbox
  useEffect(function () {
    var map = mapRef.current;
    if (!map) return;

    function setupLayer() {
      if (!map) return;

      if (map.getLayer(TRANSMISSION_LINES_LAYER)) {
        map.setLayoutProperty(
          TRANSMISSION_LINES_LAYER,
          "visibility",
          layers.transmissionLines ? "visible" : "none"
        );
        return;
      }

      if (!layers.transmissionLines) return;

      map.addSource(TRANSMISSION_LINES_SOURCE, {
        type: "geojson",
        data: "/data/transmission-lines.geojson",
      });

      map.addLayer({
        id: TRANSMISSION_LINES_LAYER,
        type: "line",
        source: TRANSMISSION_LINES_SOURCE,
        layout: {
          "line-cap": "round",
          "line-join": "round",
        },
        paint: {
          "line-color": [
            "step", ["get", "VOLTAGE"],
            "#22d3ee",  // 138-229 kV — cyan
            230, "#38bdf8",  // 230-344 kV — light blue
            345, "#818cf8",  // 345-499 kV — indigo
            500, "#a78bfa",  // 500+ kV — purple
          ],
          "line-width": [
            "step", ["get", "VOLTAGE"],
            1,      // 138-229 kV
            230, 1.5,  // 230-344 kV
            345, 2.5,  // 345-499 kV
            500, 3.5,  // 500+ kV
          ],
          "line-opacity": 0.7,
        },
      });

      map.on("click", TRANSMISSION_LINES_LAYER, function (e) {
        if (!e.features || e.features.length === 0) return;
        var feature = e.features[0];
        var props = feature.properties as Record<string, any>;

        if (typeof props.VOLTAGE === "string") props.VOLTAGE = parseFloat(props.VOLTAGE);

        if (popupRef.current) popupRef.current.remove();

        popupRef.current = new mapboxgl.Popup({ offset: 12, maxWidth: "320px" })
          .setLngLat(e.lngLat)
          .setHTML(buildTransmissionLinePopupHTML(props))
          .addTo(map!);
      });

      map.on("mouseenter", TRANSMISSION_LINES_LAYER, function () {
        map!.getCanvas().style.cursor = "pointer";
      });
      map.on("mouseleave", TRANSMISSION_LINES_LAYER, function () {
        map!.getCanvas().style.cursor = "";
      });
    }

    if (mapLoaded.current) {
      setupLayer();
    } else {
      map.on("load", setupLayer);
    }
  }, [layers.transmissionLines, buildTransmissionLinePopupHTML]);

  // Toggle queue withdrawals layer based on checkbox
  useEffect(function () {
    var map = mapRef.current;
    if (!map) return;

    function setupLayer() {
      if (!map) return;

      if (map.getLayer(QUEUE_WITHDRAWALS_LAYER)) {
        map.setLayoutProperty(
          QUEUE_WITHDRAWALS_LAYER,
          "visibility",
          layers.queueWithdrawals ? "visible" : "none"
        );
        return;
      }

      if (!layers.queueWithdrawals) return;

      map.addSource(QUEUE_WITHDRAWALS_SOURCE, {
        type: "geojson",
        data: "/data/queue-withdrawals.geojson",
      });

      map.addLayer({
        id: QUEUE_WITHDRAWALS_LAYER,
        type: "symbol",
        source: QUEUE_WITHDRAWALS_SOURCE,
        layout: {
          "icon-image": TRIANGLE_ICON,
          "icon-size": [
            "interpolate", ["linear"], ["get", "total_mw"],
            50, 0.4,
            500, 0.7,
            2000, 1.0,
          ],
          "icon-allow-overlap": true,
        },
        paint: {
          "icon-color": "#f97316",
          "icon-opacity": 0.85,
        },
      });

      map.on("click", QUEUE_WITHDRAWALS_LAYER, function (e) {
        if (!e.features || e.features.length === 0) return;
        var feature = e.features[0];
        var coords = (feature.geometry as GeoJSON.Point).coordinates.slice() as [number, number];
        var props = feature.properties as Record<string, any>;

        if (typeof props.total_mw === "string") props.total_mw = parseFloat(props.total_mw);

        if (popupRef.current) popupRef.current.remove();

        popupRef.current = new mapboxgl.Popup({ offset: 12, maxWidth: "320px" })
          .setLngLat(coords)
          .setHTML(buildQueuePopupHTML(props))
          .addTo(map!);
      });

      map.on("mouseenter", QUEUE_WITHDRAWALS_LAYER, function () {
        map!.getCanvas().style.cursor = "pointer";
      });
      map.on("mouseleave", QUEUE_WITHDRAWALS_LAYER, function () {
        map!.getCanvas().style.cursor = "";
      });
    }

    if (mapLoaded.current) {
      setupLayer();
    } else {
      map.on("load", setupLayer);
    }
  }, [layers.queueWithdrawals, buildQueuePopupHTML]);

  // Load scored sites on mount — always-visible star layer
  useEffect(function () {
    var map = mapRef.current;
    if (!map) return;

    function setupScoredLayer() {
      if (!map) return;
      if (map.getSource(SCORED_SITES_SOURCE)) return;

      fetch("/data/scored-sites.geojson")
        .then(function (res) { return res.json(); })
        .then(function (geojson) {
          // Populate sidebar state
          var sites: ScoredSite[] = geojson.features
            .map(function (f: any) { return f.properties as ScoredSite; })
            .sort(function (a: ScoredSite, b: ScoredSite) { return b.composite_score - a.composite_score; });
          setScoredSites(sites);

          // Add source + layer if map is still alive
          if (!map || map.getSource(SCORED_SITES_SOURCE)) return;

          map.addSource(SCORED_SITES_SOURCE, {
            type: "geojson",
            data: geojson,
          });

          map.addLayer({
            id: SCORED_SITES_LAYER,
            type: "symbol",
            source: SCORED_SITES_SOURCE,
            layout: {
              "icon-image": STAR_ICON,
              "icon-size": [
                "interpolate", ["linear"], ["get", "composite_score"],
                50, 0.5,
                70, 0.7,
                85, 0.9,
                95, 1.1,
              ],
              "icon-allow-overlap": true,
            },
            paint: {
              "icon-color": [
                "interpolate", ["linear"], ["get", "composite_score"],
                50, "#a16207",
                70, "#ca8a04",
                85, "#eab308",
                95, "#facc15",
              ],
              "icon-opacity": 0.95,
              "icon-halo-color": "#000000",
              "icon-halo-width": 0.5,
            },
          });

          // Click handler
          map.on("click", SCORED_SITES_LAYER, function (e) {
            if (!e.features || e.features.length === 0) return;
            var props = e.features[0].properties as Record<string, any>;
            // Parse numeric values that Mapbox stringifies
            var site: ScoredSite = {
              plant_name: props.plant_name,
              state: props.state,
              latitude: parseFloat(props.latitude),
              longitude: parseFloat(props.longitude),
              total_capacity_mw: parseFloat(props.total_capacity_mw),
              fuel_type: props.fuel_type,
              status: props.status,
              planned_retirement_date: props.planned_retirement_date || undefined,
              composite_score: parseFloat(props.composite_score),
              power_access: parseFloat(props.power_access),
              grid_capacity: parseFloat(props.grid_capacity),
              site_characteristics: parseFloat(props.site_characteristics),
              connectivity: parseFloat(props.connectivity),
              risk_factors: parseFloat(props.risk_factors),
              nearest_sub_name: props.nearest_sub_name,
              nearest_sub_distance_miles: parseFloat(props.nearest_sub_distance_miles),
              nearest_sub_voltage_kv: parseFloat(props.nearest_sub_voltage_kv),
            };

            if (popupRef.current) popupRef.current.remove();
            var coords = (e.features[0].geometry as GeoJSON.Point).coordinates.slice() as [number, number];
            popupRef.current = new mapboxgl.Popup({ offset: 14, maxWidth: "340px" })
              .setLngLat(coords)
              .setHTML(buildScoredSitePopupHTML(site))
              .addTo(map!);
          });

          map.on("mouseenter", SCORED_SITES_LAYER, function () {
            map!.getCanvas().style.cursor = "pointer";
          });
          map.on("mouseleave", SCORED_SITES_LAYER, function () {
            map!.getCanvas().style.cursor = "";
          });
        });
    }

    if (mapLoaded.current) {
      setupScoredLayer();
    } else {
      map.on("load", setupScoredLayer);
    }
  }, [buildScoredSitePopupHTML]);

  // Apply filters to scored sites map layer
  useEffect(function () {
    var map = mapRef.current;
    if (!map || !map.getLayer(SCORED_SITES_LAYER)) return;

    var conditions: any[] = ["all"];
    conditions.push([">=", ["get", "total_capacity_mw"], minMW]);
    if (selectedState) {
      conditions.push(["==", ["get", "state"], selectedState]);
    }
    map.setFilter(SCORED_SITES_LAYER, conditions);
  }, [minMW, selectedState]);

  // Apply filters to power plants map layer
  useEffect(function () {
    var map = mapRef.current;
    if (!map || !map.getLayer(POWER_PLANTS_LAYER)) return;

    var conditions: any[] = ["all"];
    conditions.push([">=", ["get", "total_capacity_mw"], minMW]);
    if (selectedState) {
      conditions.push(["==", ["get", "state"], selectedState]);
    }
    map.setFilter(POWER_PLANTS_LAYER, conditions);
  }, [minMW, selectedState]);

  return (
    <div className="flex h-screen w-screen overflow-hidden">
      {/* Sidebar */}
      <div className="w-1/4 min-w-[280px] h-full bg-[#1B2A4A] text-white overflow-y-auto flex flex-col">
        {/* Header */}
        <div className="px-5 pt-6 pb-4 border-b border-white/10">
          <h1 className="text-2xl font-bold tracking-tight">GridSite</h1>
          <p className="text-sm text-slate-400 mt-1">
            Adaptive Reuse Site Intelligence
          </p>
        </div>

        {/* Data Layers */}
        <div className="border-b border-white/10">
          <button
            onClick={() => setLayersOpen(!layersOpen)}
            className="w-full px-5 py-3 flex items-center justify-between text-xs font-semibold uppercase tracking-widest text-slate-300 hover:text-white"
          >
            Data Layers
            <span>{layersOpen ? "−" : "+"}</span>
          </button>
          {layersOpen && (
            <div className="px-5 pb-4 space-y-2.5">
              <label className="flex items-center gap-2.5 text-sm text-slate-300 cursor-pointer">
                <input
                  type="checkbox"
                  checked={layers.powerPlants}
                  onChange={() => toggleLayer("powerPlants")}
                  className="accent-blue-500"
                />
                Power Plants (EIA-860)
              </label>
              <label className="flex items-center gap-2.5 text-sm text-slate-300 cursor-pointer">
                <input
                  type="checkbox"
                  checked={layers.substations}
                  onChange={() => toggleLayer("substations")}
                  className="accent-blue-500"
                />
                Substations (HIFLD)
              </label>
              <label className="flex items-center gap-2.5 text-sm text-slate-300 cursor-pointer">
                <input
                  type="checkbox"
                  checked={layers.transmissionLines}
                  onChange={() => toggleLayer("transmissionLines")}
                  className="accent-blue-500"
                />
                Transmission Lines (HIFLD)
              </label>
              <label className="flex items-center gap-2.5 text-sm text-slate-300 cursor-pointer">
                <input
                  type="checkbox"
                  checked={layers.queueWithdrawals}
                  onChange={() => toggleLayer("queueWithdrawals")}
                  className="accent-blue-500"
                />
                Queue Withdrawals (ISO)
              </label>
            </div>
          )}
        </div>

        {/* Filters */}
        <div className="border-b border-white/10">
          <button
            onClick={() => setFiltersOpen(!filtersOpen)}
            className="w-full px-5 py-3 flex items-center justify-between text-xs font-semibold uppercase tracking-widest text-slate-300 hover:text-white"
          >
            Filters
            <span>{filtersOpen ? "−" : "+"}</span>
          </button>
          {filtersOpen && (
            <div className="px-5 pb-4 space-y-4">
              <div>
                <label className="block text-xs text-slate-400 mb-1.5">
                  Minimum MW Capacity: <span className="text-white font-medium">{minMW} MW</span>
                </label>
                <input
                  type="range"
                  min={50}
                  max={500}
                  value={minMW}
                  onChange={(e) => setMinMW(Number(e.target.value))}
                  className="w-full accent-blue-500"
                />
                <div className="flex justify-between text-[10px] text-slate-500 mt-0.5">
                  <span>50 MW</span>
                  <span>500 MW</span>
                </div>
              </div>
              <div>
                <label className="block text-xs text-slate-400 mb-1.5">
                  State
                </label>
                <select
                  value={selectedState}
                  onChange={(e) => setSelectedState(e.target.value)}
                  className="w-full bg-[#0f1b33] border border-white/10 rounded px-3 py-2 text-sm text-white"
                >
                  <option value="">All States</option>
                  {US_STATES.map(function (st) {
                    return (
                      <option key={st} value={st}>
                        {st}
                      </option>
                    );
                  })}
                </select>
              </div>
            </div>
          )}
        </div>

        {/* Results */}
        <div className="flex-1 flex flex-col min-h-0">
          <button
            onClick={() => setResultsOpen(!resultsOpen)}
            className="w-full px-5 py-3 flex items-center justify-between text-xs font-semibold uppercase tracking-widest text-slate-300 hover:text-white shrink-0"
          >
            Results {scoredSites.length > 0 && <span className="text-slate-500 normal-case tracking-normal font-normal">({filteredSites.length})</span>}
            <span>{resultsOpen ? "−" : "+"}</span>
          </button>
          {resultsOpen && (
            <div className="px-5 pb-4 space-y-2 overflow-y-auto flex-1">
              {scoredSites.length === 0 && (
                <p className="text-xs text-slate-500 text-center pt-2">
                  Loading scored sites...
                </p>
              )}
              {scoredSites.length > 0 && filteredSites.length === 0 && (
                <p className="text-xs text-slate-500 text-center pt-4 pb-2">
                  No sites match current filters
                </p>
              )}
              {filteredSites.map(function (site, idx) {
                var scoreColor = site.composite_score >= 85 ? "bg-yellow-500 text-black"
                  : site.composite_score >= 75 ? "bg-yellow-600 text-black"
                  : "bg-yellow-700 text-white";
                return (
                  <button
                    key={site.plant_name + "-" + site.state}
                    onClick={() => flyToSite(site)}
                    className="w-full text-left bg-[#0f1b33] rounded-lg p-3 border border-white/5 hover:border-yellow-500/30 hover:bg-[#132040] transition-colors"
                  >
                    <div className="flex items-start justify-between gap-2">
                      <div className="min-w-0 flex-1">
                        <div className="text-sm font-medium truncate">
                          <span className="text-slate-500 mr-1.5">{idx + 1}.</span>
                          {site.plant_name}
                        </div>
                        <div className="text-xs text-slate-400 mt-0.5">
                          {site.state} &middot; {site.total_capacity_mw.toLocaleString()} MW
                        </div>
                        <div className="text-[11px] text-slate-500 mt-0.5">
                          {site.nearest_sub_distance_miles} mi to {site.nearest_sub_voltage_kv} kV sub
                        </div>
                      </div>
                      <div className={"text-xs font-bold rounded px-2 py-1 shrink-0 " + scoreColor}>
                        {site.composite_score}
                      </div>
                    </div>
                  </button>
                );
              })}
            </div>
          )}
        </div>
      </div>

      {/* Map */}
      <div className="flex-1 h-full relative">
        <div ref={mapContainer} className="w-full h-full" />

        {/* Legend */}
        <div className="absolute bottom-6 right-2 z-10">
          {legendOpen ? (
            <div className="bg-[#1B2A4A]/90 backdrop-blur-sm border border-white/10 rounded-lg px-3 py-2.5 text-xs text-slate-200 min-w-[180px]">
              <button
                onClick={() => setLegendOpen(false)}
                className="w-full flex items-center justify-between mb-2"
              >
                <span className="font-semibold text-[11px] uppercase tracking-wider text-slate-300">Legend</span>
                <span className="text-slate-400 hover:text-white text-sm leading-none">&times;</span>
              </button>
              <div className="space-y-1.5">
                <div className="flex items-center gap-2">
                  <span className="text-yellow-400 text-sm leading-none">&#9733;</span>
                  <span>Scored Site</span>
                </div>
                <div className="flex items-center gap-2">
                  <span className="inline-block w-2.5 h-2.5 rounded-full bg-[#22c55e]"></span>
                  <span>Operating Plant</span>
                </div>
                <div className="flex items-center gap-2">
                  <span className="inline-block w-2.5 h-2.5 rounded-full bg-[#f97316]"></span>
                  <span>Retiring Plant</span>
                </div>
                <div className="flex items-center gap-2">
                  <span className="inline-block w-2.5 h-2.5 rounded-full bg-[#ef4444]"></span>
                  <span>Retired Plant</span>
                </div>
                <div className="flex items-center gap-2">
                  <span className="text-orange-500 text-[10px] leading-none">&#9650;</span>
                  <span>Queue Withdrawal</span>
                </div>
                <div className="border-t border-white/10 my-1.5"></div>
                <div className="flex items-center gap-2">
                  <span className="inline-block w-2.5 h-2.5 rotate-45 bg-[#22d3ee]"></span>
                  <span>138-229 kV Sub</span>
                </div>
                <div className="flex items-center gap-2">
                  <span className="inline-block w-2.5 h-2.5 rotate-45 bg-[#38bdf8]"></span>
                  <span>230-344 kV Sub</span>
                </div>
                <div className="flex items-center gap-2">
                  <span className="inline-block w-2.5 h-2.5 rotate-45 bg-[#818cf8]"></span>
                  <span>345 kV+ Sub</span>
                </div>
                <div className="border-t border-white/10 my-1.5"></div>
                <div className="flex items-center gap-2">
                  <span className="inline-block w-4 h-[1px] bg-[#22d3ee] rounded"></span>
                  <span>138-229 kV Line</span>
                </div>
                <div className="flex items-center gap-2">
                  <span className="inline-block w-4 h-[2px] bg-[#38bdf8] rounded"></span>
                  <span>230-344 kV Line</span>
                </div>
                <div className="flex items-center gap-2">
                  <span className="inline-block w-4 h-[3px] bg-[#818cf8] rounded"></span>
                  <span>345-499 kV Line</span>
                </div>
                <div className="flex items-center gap-2">
                  <span className="inline-block w-4 h-[4px] bg-[#a78bfa] rounded"></span>
                  <span>500 kV+ Line</span>
                </div>
              </div>
            </div>
          ) : (
            <button
              onClick={() => setLegendOpen(true)}
              className="bg-[#1B2A4A]/90 backdrop-blur-sm border border-white/10 rounded-lg px-3 py-2 text-[11px] font-semibold uppercase tracking-wider text-slate-300 hover:text-white"
            >
              Legend
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
