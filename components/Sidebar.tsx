"use client";

import { US_STATES, type ScoredSite, type LayerState, type LayerGroupState } from "../lib/constants";
import { estimateTimeToPower } from "../lib/scoring";
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
                var ttp = estimateTimeToPower(site);
                var ttpColor = ttp.tier === "green" ? "text-emerald-400 bg-emerald-400/10 border-emerald-400/20"
                  : ttp.tier === "yellow" ? "text-amber-400 bg-amber-400/10 border-amber-400/20"
                  : "text-red-400 bg-red-400/10 border-red-400/20";
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
                        <div className="flex items-center gap-2 mt-1">
                          <span className="text-[11px] text-slate-500">
                            {site.nearest_sub_distance_miles} mi to {site.nearest_sub_voltage_kv} kV sub
                          </span>
                          <span className={"text-[10px] font-semibold px-1.5 py-0.5 rounded border " + ttpColor}>
                            {ttp.label}
                          </span>
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
                    {selectedSite.status !== "custom" && selectedSite.status !== "brownfield" && <> &middot; {selectedSite.status.charAt(0).toUpperCase() + selectedSite.status.slice(1)}</>}
                  </div>
                </div>

                {/* Composite Score + TTP Badge */}
                {(function () {
                  var ttp = estimateTimeToPower(selectedSite);
                  var ttpBg = ttp.tier === "green" ? "bg-emerald-500" : ttp.tier === "yellow" ? "bg-amber-500" : "bg-red-500";
                  var ttpText = ttp.tier === "red" ? "text-white" : "text-black";
                  return (
                    <div className="flex items-center gap-3">
                      <div className={"text-2xl font-bold rounded-lg px-4 py-2 " + (selectedSite.composite_score >= 85 ? "bg-yellow-500 text-black" : selectedSite.composite_score >= 75 ? "bg-yellow-600 text-black" : "bg-yellow-700 text-white")}>
                        {selectedSite.composite_score}
                      </div>
                      <div>
                        <div className="text-xs text-slate-400">Composite Score</div>
                        <div className={"inline-block text-[11px] font-bold rounded px-2 py-0.5 mt-1 " + ttpBg + " " + ttpText}>
                          {ttp.label}
                        </div>
                        <span className="text-[11px] text-slate-500 ml-1.5">{ttp.months}</span>
                      </div>
                    </div>
                  );
                })()}

                {/* --- Time to Power (50%) --- */}
                {(function () {
                  var s = selectedSite;
                  var val = s.time_to_power;
                  var barColor = val >= 80 ? "#eab308" : val >= 60 ? "#a3a3a3" : "#78716c";
                  var subColor = function (v: number) { return v >= 80 ? "#eab308" : v >= 60 ? "#a3a3a3" : "#78716c"; };
                  var isPowerPlant = s.fuel_type !== "Custom" && s.fuel_type !== "Brownfield";
                  return (
                    <div>
                      <div className="flex justify-between text-xs mb-1">
                        <span className="text-slate-300 font-semibold">Time to Power <span className="text-slate-500 font-normal">(50%)</span></span>
                        <span className="font-medium" style={{ color: barColor }}>{val}</span>
                      </div>
                      <div className="w-full bg-[#0f1b33] rounded-full h-1.5 mb-2">
                        <div className="h-1.5 rounded-full" style={{ width: val + "%", backgroundColor: barColor }}></div>
                      </div>
                      <div className="pl-3 space-y-1 border-l border-white/5">
                        <div className="text-[11px] text-slate-400 flex justify-between">
                          <span>Substation Distance</span>
                          <span style={{ color: subColor(s.sub_distance_score) }} className="font-medium">{s.sub_distance_score} <span className="text-slate-500">({s.nearest_sub_distance_miles} mi)</span></span>
                        </div>
                        <div className="text-[11px] text-slate-400 flex justify-between">
                          <span>Substation Voltage</span>
                          <span style={{ color: subColor(s.sub_voltage_score) }} className="font-medium">{s.sub_voltage_score} <span className="text-slate-500">({s.nearest_sub_voltage_kv} kV)</span></span>
                        </div>
                        {isPowerPlant && (
                          <div className="text-[11px] text-slate-400 flex justify-between">
                            <span>Generation Capacity</span>
                            <span style={{ color: subColor(s.gen_capacity_score) }} className="font-medium">{s.gen_capacity_score} <span className="text-slate-500">({s.total_capacity_mw.toLocaleString()} MW)</span></span>
                          </div>
                        )}
                        <div className="text-[11px] text-slate-400 flex justify-between">
                          <span>Transmission Lines</span>
                          <span style={{ color: subColor(s.tx_lines_score) }} className="font-medium">{s.tx_lines_score} <span className="text-slate-500">({s.nearest_sub_lines} lines)</span></span>
                        </div>
                        <div className="text-[11px] text-slate-400 flex justify-between">
                          <span>Queue Withdrawals</span>
                          <span style={{ color: subColor(s.queue_withdrawal_score) }} className="font-medium">{s.queue_withdrawal_score} <span className="text-slate-500">({s.queue_count_20mi} / {Math.round(s.queue_mw_20mi).toLocaleString()} MW)</span></span>
                        </div>
                        <div className="text-[11px] text-slate-400 flex justify-between">
                          <span>Grid Pricing (LMP)</span>
                          <span style={{ color: subColor(s.lmp_score) }} className="font-medium">{s.lmp_score} <span className="text-slate-500">(${s.nearest_lmp_avg}/MWh)</span></span>
                        </div>
                      </div>
                    </div>
                  );
                })()}

                {/* --- Site Readiness (20%) --- */}
                {(function () {
                  var s = selectedSite;
                  var val = s.site_readiness;
                  var barColor = val >= 80 ? "#eab308" : val >= 60 ? "#a3a3a3" : "#78716c";
                  var subColor = function (v: number) { return v >= 80 ? "#eab308" : v >= 60 ? "#a3a3a3" : "#78716c"; };
                  var isPowerPlant = s.fuel_type !== "Custom" && s.fuel_type !== "Brownfield";
                  return (
                    <div>
                      <div className="flex justify-between text-xs mb-1">
                        <span className="text-slate-300 font-semibold">Site Readiness <span className="text-slate-500 font-normal">(20%)</span></span>
                        <span className="font-medium" style={{ color: barColor }}>{val}</span>
                      </div>
                      <div className="w-full bg-[#0f1b33] rounded-full h-1.5 mb-2">
                        <div className="h-1.5 rounded-full" style={{ width: val + "%", backgroundColor: barColor }}></div>
                      </div>
                      {isPowerPlant ? (
                        <div className="pl-3 space-y-1 border-l border-white/5">
                          <div className="text-[11px] text-slate-400 flex justify-between">
                            <span>Fuel Type Suitability</span>
                            <span style={{ color: subColor(s.fuel_type_score) }} className="font-medium">{s.fuel_type_score}</span>
                          </div>
                          <div className="text-[11px] text-slate-400 flex justify-between">
                            <span>Capacity Scale</span>
                            <span style={{ color: subColor(s.capacity_scale_score) }} className="font-medium">{s.capacity_scale_score}</span>
                          </div>
                        </div>
                      ) : (
                        <div className="pl-3 border-l border-white/5">
                          <div className="text-[11px] text-slate-500">Base reuse score (assessed/cleared site)</div>
                        </div>
                      )}
                    </div>
                  );
                })()}

                {/* --- Connectivity (15%) --- */}
                {(function () {
                  var s = selectedSite;
                  var val = s.connectivity;
                  var barColor = val >= 80 ? "#eab308" : val >= 60 ? "#a3a3a3" : "#78716c";
                  var subColor = function (v: number) { return v >= 80 ? "#eab308" : v >= 60 ? "#a3a3a3" : "#78716c"; };
                  return (
                    <div>
                      <div className="flex justify-between text-xs mb-1">
                        <span className="text-slate-300 font-semibold">Connectivity <span className="text-slate-500 font-normal">(15%)</span></span>
                        <span className="font-medium" style={{ color: barColor }}>{val}</span>
                      </div>
                      <div className="w-full bg-[#0f1b33] rounded-full h-1.5 mb-2">
                        <div className="h-1.5 rounded-full" style={{ width: val + "%", backgroundColor: barColor }}></div>
                      </div>
                      <div className="pl-3 space-y-1 border-l border-white/5">
                        <div className="text-[11px] text-slate-400 flex justify-between">
                          <span>Longitude Proximity</span>
                          <span style={{ color: subColor(s.longitude_score) }} className="font-medium">{s.longitude_score}</span>
                        </div>
                        <div className="text-[11px] text-slate-400 flex justify-between">
                          <span>Latitude Band</span>
                          <span style={{ color: subColor(s.latitude_score) }} className="font-medium">{s.latitude_score}</span>
                        </div>
                        <div className="text-[11px] text-slate-400 flex justify-between">
                          <span>Broadband Coverage</span>
                          <span style={{ color: subColor(s.broadband_score) }} className="font-medium">{s.broadband_score}</span>
                        </div>
                      </div>
                    </div>
                  );
                })()}

                {/* --- Risk Factors (15%) --- */}
                {(function () {
                  var s = selectedSite;
                  var val = s.risk_factors;
                  var barColor = val >= 80 ? "#eab308" : val >= 60 ? "#a3a3a3" : "#78716c";
                  var subColor = function (v: number) { return v >= 80 ? "#eab308" : v >= 60 ? "#a3a3a3" : "#78716c"; };
                  var isPowerPlant = s.fuel_type !== "Custom" && s.fuel_type !== "Brownfield";
                  return (
                    <div>
                      <div className="flex justify-between text-xs mb-1">
                        <span className="text-slate-300 font-semibold">Risk Factors <span className="text-slate-500 font-normal">(15%)</span></span>
                        <span className="font-medium" style={{ color: barColor }}>{val}</span>
                      </div>
                      <div className="w-full bg-[#0f1b33] rounded-full h-1.5 mb-2">
                        <div className="h-1.5 rounded-full" style={{ width: val + "%", backgroundColor: barColor }}></div>
                      </div>
                      <div className="pl-3 space-y-1 border-l border-white/5">
                        <div className="text-[11px] text-slate-400 flex justify-between">
                          <span>Contamination Risk</span>
                          <span style={{ color: subColor(s.contamination_score) }} className="font-medium">{s.contamination_score}</span>
                        </div>
                        {isPowerPlant && (
                          <div className="text-[11px] text-slate-400 flex justify-between">
                            <span>Operational Status</span>
                            <span style={{ color: subColor(s.operational_status_score) }} className="font-medium">{s.operational_status_score}</span>
                          </div>
                        )}
                        <div className="text-[11px] text-slate-400 flex justify-between">
                          <span>Flood Zone Exposure</span>
                          <span style={{ color: subColor(s.flood_zone_score) }} className="font-medium">{s.flood_zone_score}</span>
                        </div>
                      </div>
                    </div>
                  );
                })()}

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
                  <div className="text-xs text-slate-400 flex justify-between">
                    <span>Connected Lines</span>
                    <span className="text-slate-200 font-medium">{selectedSite.nearest_sub_lines}</span>
                  </div>
                </div>

                {/* Nearest LMP Node */}
                {selectedSite.nearest_lmp_node && (
                  <div className="space-y-1.5">
                    <div className="text-xs font-semibold text-slate-300">Nearest LMP Pricing Node</div>
                    <div className="text-xs text-slate-400 flex justify-between">
                      <span>Node</span>
                      <span className="text-slate-200 font-medium">{selectedSite.nearest_lmp_node}</span>
                    </div>
                    <div className="text-xs text-slate-400 flex justify-between">
                      <span>Avg LMP</span>
                      <span className="text-slate-200 font-medium">${selectedSite.nearest_lmp_avg}/MWh</span>
                    </div>
                  </div>
                )}

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
