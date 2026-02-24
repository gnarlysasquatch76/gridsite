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
  });
  var [layerGroupOpen, setLayerGroupOpen] = useState<LayerGroupState>({
    infrastructure: true,
    capacity: false,
    risk: false,
    connectivity: false,
  });

  var [minMW, setMinMW] = useState(50);
  var [selectedState, setSelectedState] = useState("");
  var [scoredSites, setScoredSites] = useState<ScoredSite[]>([]);
  var [activeTab, setActiveTab] = useState<"sites" | "detail" | "export">("sites");
  var [selectedSite, setSelectedSite] = useState<ScoredSite | null>(null);

  var filteredSites = useMemo(function () {
    return scoredSites.filter(function (site) {
      if (site.total_capacity_mw < minMW) return false;
      if (selectedState && site.state !== selectedState) return false;
      return true;
    });
  }, [scoredSites, minMW, selectedState]);

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
        scoredSites={scoredSites}
        filteredSites={filteredSites}
        minMW={minMW}
        selectedState={selectedState}
        onMinMWChange={setMinMW}
        onSelectedStateChange={setSelectedState}
        onFlyToSite={handleFlyToSite}
      />
      <MapComponent
        ref={mapHandleRef}
        layers={layers}
        minMW={minMW}
        selectedState={selectedState}
        onScoredSitesLoaded={handleScoredSitesLoaded}
      />
    </div>
  );
}
