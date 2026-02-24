"use client";

import { useRef, useState, useMemo, useCallback } from "react";
import Sidebar from "../components/Sidebar";
import MapComponent, { type MapHandle } from "../components/Map";
import { type ScoredSite, type LayerState, type LayerGroupState } from "../lib/constants";

export default function Home() {
  var mapHandleRef = useRef<MapHandle>(null);

  var [layersOpen, setLayersOpen] = useState(true);
  var [layers, setLayers] = useState<LayerState>({
    powerPlants: false,
    substations: false,
    transmissionLines: false,
    queueWithdrawals: false,
    floodZones: false,
    broadband: false,
    brownfields: false,
    dataCenters: false,
    utilityTerritories: false,
    lmpNodes: false,
    opportunities: false,
  });
  var [layerGroupOpen, setLayerGroupOpen] = useState<LayerGroupState>({
    infrastructure: true,
    capacity: false,
    risk: false,
    connectivity: false,
  });

  var [minMW, setMinMW] = useState(50);
  var [selectedState, setSelectedState] = useState("");
  var [siteTypeFilter, setSiteTypeFilter] = useState("all");
  var [scoredSites, setScoredSites] = useState<ScoredSite[]>([]);
  var [opportunitySites, setOpportunitySites] = useState<ScoredSite[]>([]);
  var [activeTab, setActiveTab] = useState<"sites" | "detail" | "export">("sites");
  var [selectedSite, setSelectedSite] = useState<ScoredSite | null>(null);

  var allSites = useMemo(function () {
    return [...scoredSites, ...opportunitySites].sort(function (a, b) {
      return b.composite_score - a.composite_score;
    });
  }, [scoredSites, opportunitySites]);

  var filteredSites = useMemo(function () {
    return allSites.filter(function (site) {
      if (site.total_capacity_mw < minMW && !site.opportunity_type) return false;
      if (selectedState && site.state !== selectedState) return false;
      if (siteTypeFilter !== "all") {
        if (siteTypeFilter === "scored" && site.opportunity_type) return false;
        if (siteTypeFilter === "opportunity" && !site.opportunity_type) return false;
        if (siteTypeFilter === "retired_plant" && site.opportunity_type !== "retired_plant") return false;
        if (siteTypeFilter === "adaptive_reuse" && site.opportunity_type !== "adaptive_reuse") return false;
        if (siteTypeFilter === "greenfield" && site.opportunity_type !== "greenfield") return false;
      }
      return true;
    });
  }, [allSites, minMW, selectedState, siteTypeFilter]);

  function toggleLayer(key: keyof LayerState) {
    setLayers(function (prev) { return { ...prev, [key]: !prev[key] }; });
  }

  function toggleLayerGroup(group: keyof LayerGroupState) {
    setLayerGroupOpen(function (prev) { return { ...prev, [group]: !prev[group] }; });
  }

  function setGroupLayers(keys: (keyof LayerState)[], value: boolean) {
    setLayers(function (prev) {
      var next = { ...prev };
      keys.forEach(function (k) { next[k] = value; });
      return next;
    });
  }

  var handleFlyToSite = useCallback(function (site: ScoredSite) {
    setSelectedSite(site);
    setActiveTab("detail");
    mapHandleRef.current?.flyToSite(site);
  }, []);

  var handleScoredSitesLoaded = useCallback(function (sites: ScoredSite[]) {
    setScoredSites(sites);
  }, []);

  var handleOpportunitySitesLoaded = useCallback(function (sites: ScoredSite[]) {
    setOpportunitySites(sites);
  }, []);

  return (
    <div className="flex h-screen w-screen overflow-hidden">
      <Sidebar
        layers={layers}
        layersOpen={layersOpen}
        layerGroupOpen={layerGroupOpen}
        onToggleLayersOpen={() => setLayersOpen(!layersOpen)}
        onToggleLayer={toggleLayer}
        onToggleLayerGroup={toggleLayerGroup}
        onSetGroupLayers={setGroupLayers}
        activeTab={activeTab}
        onTabChange={setActiveTab}
        selectedSite={selectedSite}
        scoredSites={allSites}
        filteredSites={filteredSites}
        minMW={minMW}
        selectedState={selectedState}
        siteTypeFilter={siteTypeFilter}
        onMinMWChange={setMinMW}
        onSelectedStateChange={setSelectedState}
        onSiteTypeFilterChange={setSiteTypeFilter}
        onFlyToSite={handleFlyToSite}
      />
      <MapComponent
        ref={mapHandleRef}
        layers={layers}
        minMW={minMW}
        selectedState={selectedState}
        onScoredSitesLoaded={handleScoredSitesLoaded}
        onOpportunitySitesLoaded={handleOpportunitySitesLoaded}
      />
    </div>
  );
}
