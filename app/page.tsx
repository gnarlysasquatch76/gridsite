"use client";

import { useEffect, useRef } from "react";
import mapboxgl from "mapbox-gl";
import "mapbox-gl/dist/mapbox-gl.css";

var MAPBOX_TOKEN = process.env.NEXT_PUBLIC_MAPBOX_TOKEN || "";

var markets = [
  {
    name: "Jackson Hole", state: "WY", lat: 43.4799, lng: -110.7624,
    mivi: 92, isolation: 95, housingGap: 94, employer: 90, regulatory: 82, infrastructure: 78,
    medianHome: "$1.78M", avgWage: "$22/hr", closureDays: 34, topEmployer: "Jackson Hole Mountain Resort"
  },
  {
    name: "Telluride", state: "CO", lat: 37.9375, lng: -107.8123,
    mivi: 89, isolation: 97, housingGap: 91, employer: 85, regulatory: 80, infrastructure: 72,
    medianHome: "$1.9M", avgWage: "$24/hr", closureDays: 28, topEmployer: "Telluride Ski Resort"
  },
  {
    name: "Big Sky", state: "MT", lat: 45.2833, lng: -111.4014,
    mivi: 86, isolation: 88, housingGap: 87, employer: 88, regulatory: 76, infrastructure: 70,
    medianHome: "$1.6M", avgWage: "$21/hr", closureDays: 22, topEmployer: "Big Sky Resort"
  },
  {
    name: "Vail", state: "CO", lat: 39.6403, lng: -106.3742,
    mivi: 84, isolation: 82, housingGap: 88, employer: 92, regulatory: 78, infrastructure: 80,
    medianHome: "$2.5M", avgWage: "$20/hr", closureDays: 18, topEmployer: "Vail Resorts"
  },
  {
    name: "Steamboat Springs", state: "CO", lat: 40.485, lng: -106.8317,
    mivi: 81, isolation: 75, housingGap: 82, employer: 84, regulatory: 84, infrastructure: 82,
    medianHome: "$1.2M", avgWage: "$21/hr", closureDays: 15, topEmployer: "Steamboat Resort"
  },
  {
    name: "Park City", state: "UT", lat: 40.6461, lng: -111.498,
    mivi: 78, isolation: 65, housingGap: 85, employer: 86, regulatory: 80, infrastructure: 88,
    medianHome: "$3.2M", avgWage: "$22/hr", closureDays: 8, topEmployer: "Deer Valley Resort"
  },
  {
    name: "Aspen", state: "CO", lat: 39.1911, lng: -106.8175,
    mivi: 83, isolation: 80, housingGap: 90, employer: 87, regulatory: 72, infrastructure: 75,
    medianHome: "$3.5M", avgWage: "$25/hr", closureDays: 20, topEmployer: "Aspen Skiing Company"
  },
  {
    name: "Breckenridge", state: "CO", lat: 39.4817, lng: -106.0384,
    mivi: 77, isolation: 78, housingGap: 80, employer: 82, regulatory: 76, infrastructure: 82,
    medianHome: "$1.4M", avgWage: "$20/hr", closureDays: 18, topEmployer: "Vail Resorts"
  },
  {
    name: "Whitefish", state: "MT", lat: 48.4106, lng: -114.3528,
    mivi: 74, isolation: 70, housingGap: 76, employer: 78, regulatory: 80, infrastructure: 76,
    medianHome: "$850K", avgWage: "$19/hr", closureDays: 12, topEmployer: "Whitefish Mountain Resort"
  },
  {
    name: "Sun Valley", state: "ID", lat: 43.6977, lng: -114.3514,
    mivi: 79, isolation: 76, housingGap: 83, employer: 80, regulatory: 78, infrastructure: 74,
    medianHome: "$1.5M", avgWage: "$21/hr", closureDays: 14, topEmployer: "Sun Valley Resort"
  },
];

function getScoreColor(score: number): string {
  if (score >= 90) return "#c62828";
  if (score >= 80) return "#e65100";
  if (score >= 70) return "#f9a825";
  return "#2e7d32";
}

function getMarkerSize(mivi: number): number {
  if (mivi >= 90) return 20;
  if (mivi >= 80) return 16;
  return 13;
}

function makeBar(label: string, score: number): string {
  var color = getScoreColor(score);
  return "<div style='margin:4px 0;'>" +
    "<div style='display:flex;justify-content:space-between;font-size:11px;margin-bottom:2px;'>" +
    "<span>" + label + "</span><span style='font-weight:bold;color:" + color + ";'>" + score + "</span></div>" +
    "<div style='background:#e0e0e0;border-radius:3px;height:6px;'>" +
    "<div style='background:" + color + ";border-radius:3px;height:6px;width:" + score + "%;'></div>" +
    "</div></div>";
}

function makePopup(m: any): string {
  var color = getScoreColor(m.mivi);
  return "<div style='font-family:Arial;padding:8px;min-width:240px;'>" +
    "<div style='display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;'>" +
    "<div><strong style='font-size:15px;color:#1B2A4A;'>" + m.name + "</strong>" +
    "<br/><span style='color:#666;font-size:11px;'>" + m.state + "</span></div>" +
    "<div style='background:" + color + ";color:white;border-radius:6px;padding:4px 10px;font-size:18px;font-weight:bold;'>" + m.mivi + "</div></div>" +
    "<div style='border-top:1px solid #e0e0e0;padding-top:8px;'>" +
    makeBar("Geographic Isolation", m.isolation) +
    makeBar("Housing Gap Severity", m.housingGap) +
    makeBar("Employer Concentration", m.employer) +
    makeBar("Regulatory Environment", m.regulatory) +
    makeBar("Infrastructure Feasibility", m.infrastructure) +
    "</div>" +
    "<div style='border-top:1px solid #e0e0e0;margin-top:8px;padding-top:8px;font-size:11px;color:#666;'>" +
    "<div style='display:flex;justify-content:space-between;margin:2px 0;'><span>Median Home Price</span><strong style='color:#333;'>" + m.medianHome + "</strong></div>" +
    "<div style='display:flex;justify-content:space-between;margin:2px 0;'><span>Avg Resort Wage</span><strong style='color:#333;'>" + m.avgWage + "</strong></div>" +
    "<div style='display:flex;justify-content:space-between;margin:2px 0;'><span>Winter Closure Days/Yr</span><strong style='color:#333;'>" + m.closureDays + "</strong></div>" +
    "<div style='display:flex;justify-content:space-between;margin:2px 0;'><span>Top Employer</span><strong style='color:#333;'>" + m.topEmployer + "</strong></div>" +
    "</div></div>";
}

export default function Home() {
  var mapContainer = useRef(null);

  useEffect(function() {
    if (!mapContainer.current) return;

    var map = new mapboxgl.Map({
      container: mapContainer.current,
      style: "mapbox://styles/mapbox/dark-v11",
      center: [-109.5, 43.0],
      zoom: 5.2,
      accessToken: MAPBOX_TOKEN,
    });

    map.addControl(new mapboxgl.NavigationControl());

    map.on("load", function() {
      for (var i = 0; i < markets.length; i++) {
        var m = markets[i];
        var size = getMarkerSize(m.mivi);
        var el = document.createElement("div");
        el.style.width = size + "px";
        el.style.height = size + "px";
        el.style.backgroundColor = getScoreColor(m.mivi);
        el.style.borderRadius = "50%";
        el.style.border = "2px solid white";
        el.style.cursor = "pointer";
        el.style.boxShadow = "0 0 8px rgba(0,0,0,0.5)";

        new mapboxgl.Marker(el)
          .setLngLat([m.lng, m.lat])
          .setPopup(new mapboxgl.Popup({ offset: 15, maxWidth: "300px" }).setHTML(makePopup(m)))
          .addTo(map);
      }
    });

    return function() { map.remove(); };
  }, []);

  return (
    <div style={{ position: "relative", width: "100vw", height: "100vh" }}>
      <div style={{ position: "absolute", top: 20, left: 20, zIndex: 1, backgroundColor: "rgba(27,42,74,0.95)", padding: "14px 22px", borderRadius: "8px", boxShadow: "0 2px 12px rgba(0,0,0,0.3)" }}>
        <span style={{ color: "white", fontFamily: "Arial", fontSize: "20px", fontWeight: "bold" }}>GridSite</span>
        <span style={{ color: "#2E75B6", fontFamily: "Arial", fontSize: "12px", marginLeft: "10px", letterSpacing: "1px" }}>MIVI MODULE</span>
      </div>
      <div style={{ position: "absolute", bottom: 30, left: 20, zIndex: 1, backgroundColor: "rgba(27,42,74,0.9)", padding: "12px 16px", borderRadius: "8px", fontFamily: "Arial", fontSize: "11px", color: "white" }}>
        <div style={{ fontWeight: "bold", marginBottom: "6px" }}>MIVI Score</div>
        <div style={{ display: "flex", alignItems: "center", gap: "6px", marginBottom: "3px" }}>
          <div style={{ width: "10px", height: "10px", borderRadius: "50%", backgroundColor: "#c62828" }}></div>
          <span>90+ Critical Need</span>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: "6px", marginBottom: "3px" }}>
          <div style={{ width: "10px", height: "10px", borderRadius: "50%", backgroundColor: "#e65100" }}></div>
          <span>80-89 High Need</span>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: "6px", marginBottom: "3px" }}>
          <div style={{ width: "10px", height: "10px", borderRadius: "50%", backgroundColor: "#f9a825" }}></div>
          <span>70-79 Moderate</span>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
          <div style={{ width: "10px", height: "10px", borderRadius: "50%", backgroundColor: "#2e7d32" }}></div>
          <span>Below 70</span>
        </div>
      </div>
      <div ref={mapContainer} style={{ width: "100%", height: "100%" }} />
    </div>
  );
}
