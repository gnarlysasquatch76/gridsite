"use client";

import { US_STATES, type ScoredSite, type LayerState, type LayerGroupState } from "../lib/constants";
import LayerControls from "./LayerControls";

interface SidebarProps {
  layers: LayerState;
  layersOpen: boolean;
  layerGroupOpen: LayerGroupState;
  onToggleLayersOpen: () => void;
  onToggleLayer: (key: keyof LayerState) => void;
  onToggleLayerGroup: (group: keyof LayerGroupState) => void;
  onSetGroupLayers: (keys: (keyof LayerState)[], value: boolean) => void;
  activeTab: "sites" | "detail" | "export";
  onTabChange: (tab: "sites" | "detail" | "export") => void;
  selectedSite: ScoredSite | null;
  scoredSites: ScoredSite[];
  filteredSites: ScoredSite[];
  minMW: number;
  selectedState: string;
  onMinMWChange: (value: number) => void;
  onSelectedStateChange: (value: string) => void;
  onFlyToSite: (site: ScoredSite) => void;
}

export default function Sidebar(props: SidebarProps) {
  var {
    layers, layersOpen, layerGroupOpen,
    onToggleLayersOpen, onToggleLayer, onToggleLayerGroup, onSetGroupLayers,
    activeTab, onTabChange, selectedSite,
    scoredSites, filteredSites,
    minMW, selectedState, onMinMWChange, onSelectedStateChange,
    onFlyToSite,
  } = props;

  return (
    <div className="w-1/4 min-w-[280px] h-full bg-[#1B2A4A] text-white overflow-y-auto flex flex-col">
      {/* Header */}
      <div className="px-5 pt-6 pb-4 border-b border-white/10">
        <h1 className="text-2xl font-bold tracking-tight">GridSite</h1>
        <p className="text-sm text-slate-400 mt-1">
          Adaptive Reuse Site Intelligence
        </p>
      </div>

      {/* Data Layers */}
      <LayerControls
        layers={layers}
        layersOpen={layersOpen}
        layerGroupOpen={layerGroupOpen}
        onToggleLayersOpen={onToggleLayersOpen}
        onToggleLayer={onToggleLayer}
        onToggleLayerGroup={onToggleLayerGroup}
        onSetGroupLayers={onSetGroupLayers}
      />

      {/* Tab Bar */}
      <div className="flex border-b border-white/10 shrink-0">
        <button
          onClick={() => onTabChange("sites")}
          className={"flex-1 py-2.5 text-xs font-semibold uppercase tracking-wider text-center " + (activeTab === "sites" ? "text-white border-b-2 border-yellow-500" : "text-slate-400 hover:text-slate-200")}
        >
          Scored Sites
        </button>
        <button
          onClick={() => onTabChange("detail")}
          className={"flex-1 py-2.5 text-xs font-semibold uppercase tracking-wider text-center " + (activeTab === "detail" ? "text-white border-b-2 border-yellow-500" : "text-slate-400 hover:text-slate-200")}
        >
          Site Detail
        </button>
        <button
          onClick={() => onTabChange("export")}
          className={"flex-1 py-2.5 text-xs font-semibold uppercase tracking-wider text-center " + (activeTab === "export" ? "text-white border-b-2 border-yellow-500" : "text-slate-400 hover:text-slate-200")}
        >
          Export
        </button>
      </div>

      {/* Tab Content */}
      <div className="flex-1 flex flex-col min-h-0 overflow-y-auto">
        {/* Scored Sites Tab */}
        {activeTab === "sites" && (
          <div className="flex flex-col flex-1">
            {/* Filters */}
            <div className="px-5 pt-4 pb-3 space-y-4 border-b border-white/10">
              <div>
                <label className="block text-xs text-slate-400 mb-1.5">
                  Minimum MW Capacity: <span className="text-white font-medium">{minMW} MW</span>
                </label>
                <input
                  type="range"
                  min={50}
                  max={500}
                  value={minMW}
                  onChange={(e) => onMinMWChange(Number(e.target.value))}
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
                  onChange={(e) => onSelectedStateChange(e.target.value)}
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

            {/* Results List */}
            <div className="px-5 py-3 space-y-2 overflow-y-auto flex-1">
              <div className="text-xs text-slate-500 mb-1">
                {scoredSites.length > 0 ? filteredSites.length + " sites" : ""}
              </div>
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
                    onClick={() => onFlyToSite(site)}
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
          </div>
        )}

        {/* Site Detail Tab */}
        {activeTab === "detail" && (
          <div className="px-5 py-4">
            {selectedSite ? (
              <div className="space-y-4">
                {/* Site Header */}
                <div>
                  <div className="text-lg font-bold">{selectedSite.plant_name}</div>
                  <div className="text-sm text-slate-400 mt-0.5">
                    {selectedSite.state}
                    {selectedSite.total_capacity_mw > 0 && <> &middot; {selectedSite.total_capacity_mw.toLocaleString()} MW</>}
                    {selectedSite.fuel_type !== "Custom" && <> &middot; {selectedSite.fuel_type}</>}
                    {selectedSite.status !== "custom" && <> &middot; {selectedSite.status.charAt(0).toUpperCase() + selectedSite.status.slice(1)}</>}
                  </div>
                </div>

                {/* Composite Score Badge */}
                <div className="flex items-center gap-3">
                  <div className={"text-2xl font-bold rounded-lg px-4 py-2 " + (selectedSite.composite_score >= 85 ? "bg-yellow-500 text-black" : selectedSite.composite_score >= 75 ? "bg-yellow-600 text-black" : "bg-yellow-700 text-white")}>
                    {selectedSite.composite_score}
                  </div>
                  <div className="text-xs text-slate-400">Composite Score</div>
                </div>

                {/* Score Components */}
                <div className="space-y-3">
                  {[
                    { label: "Power Access", weight: "30%", value: selectedSite.power_access },
                    { label: "Grid Capacity", weight: "20%", value: selectedSite.grid_capacity },
                    { label: "Site Characteristics", weight: "20%", value: selectedSite.site_characteristics },
                    { label: "Connectivity", weight: "15%", value: selectedSite.connectivity },
                    { label: "Risk Factors", weight: "15%", value: selectedSite.risk_factors },
                  ].map(function (comp) {
                    var barColor = comp.value >= 80 ? "#eab308" : comp.value >= 60 ? "#a3a3a3" : "#78716c";
                    return (
                      <div key={comp.label}>
                        <div className="flex justify-between text-xs mb-1">
                          <span className="text-slate-300">{comp.label} <span className="text-slate-500">({comp.weight})</span></span>
                          <span className="font-medium" style={{ color: barColor }}>{comp.value}</span>
                        </div>
                        <div className="w-full bg-[#0f1b33] rounded-full h-1.5">
                          <div className="h-1.5 rounded-full" style={{ width: comp.value + "%", backgroundColor: barColor }}></div>
                        </div>
                      </div>
                    );
                  })}
                </div>

                {/* Divider */}
                <div className="border-t border-white/10"></div>

                {/* Nearest Substation */}
                <div className="space-y-1.5">
                  <div className="text-xs font-semibold text-slate-300">Nearest 345kV+ Substation</div>
                  <div className="text-xs text-slate-400 flex justify-between">
                    <span>Name</span>
                    <span className="text-slate-200 font-medium">{selectedSite.nearest_sub_name}</span>
                  </div>
                  <div className="text-xs text-slate-400 flex justify-between">
                    <span>Distance</span>
                    <span className="text-slate-200 font-medium">{selectedSite.nearest_sub_distance_miles} mi</span>
                  </div>
                  <div className="text-xs text-slate-400 flex justify-between">
                    <span>Voltage</span>
                    <span className="text-slate-200 font-medium">{selectedSite.nearest_sub_voltage_kv} kV</span>
                  </div>
                </div>

                {/* Planned Retirement */}
                {selectedSite.planned_retirement_date && (
                  <>
                    <div className="border-t border-white/10"></div>
                    <div className="text-xs text-slate-400 flex justify-between">
                      <span>Planned Retirement</span>
                      <span className="text-orange-400 font-medium">{selectedSite.planned_retirement_date}</span>
                    </div>
                  </>
                )}
              </div>
            ) : (
              <div className="text-center pt-12">
                <div className="text-slate-500 text-sm">Select a scored site from the list or click one on the map</div>
              </div>
            )}
          </div>
        )}

        {/* Export Tab */}
        {activeTab === "export" && (
          <div className="px-5 py-8 text-center">
            <div className="text-3xl text-slate-500 mb-3">&darr;</div>
            <div className="text-sm font-semibold text-slate-300 mb-3">Export coming soon</div>
            <ul className="text-xs text-slate-500 space-y-1.5">
              <li>CSV site rankings</li>
              <li>PDF site reports</li>
              <li>GeoJSON data export</li>
            </ul>
          </div>
        )}
      </div>

      {/* Instruction */}
      <div className="px-5 py-3 border-t border-white/10 shrink-0">
        <p className="text-xs text-slate-500 text-center">
          Right-click map to score any location
        </p>
      </div>
    </div>
  );
}
