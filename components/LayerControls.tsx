"use client";

import { LAYER_GROUPS, type LayerState, type LayerGroupState } from "../lib/constants";

interface LayerControlsProps {
  layers: LayerState;
  layersOpen: boolean;
  layerGroupOpen: LayerGroupState;
  onToggleLayersOpen: () => void;
  onToggleLayer: (key: keyof LayerState) => void;
  onToggleLayerGroup: (group: keyof LayerGroupState) => void;
  onSetGroupLayers: (keys: (keyof LayerState)[], value: boolean) => void;
}

export default function LayerControls(props: LayerControlsProps) {
  var { layers, layersOpen, layerGroupOpen, onToggleLayersOpen, onToggleLayer, onToggleLayerGroup, onSetGroupLayers } = props;

  function renderGroup(
    groupKey: keyof LayerGroupState,
    label: string,
    layerKeys: readonly string[],
    checkboxes: { key: keyof LayerState; label: string }[],
  ) {
    var keys = layerKeys as unknown as (keyof LayerState)[];
    var activeCount = keys.filter(function (k) { return layers[k]; }).length;
    return (
      <div>
        <div className="flex items-center justify-between py-1.5">
          <button
            onClick={() => onToggleLayerGroup(groupKey)}
            className="flex items-center gap-1.5 text-sm text-slate-200 hover:text-white font-medium"
          >
            <span className="text-[10px]">{layerGroupOpen[groupKey] ? "\u25BE" : "\u25B8"}</span>
            {label}
            <span className="text-[11px] text-slate-500 font-normal">({activeCount}/{keys.length})</span>
          </button>
          <div className="flex gap-2 text-[11px]">
            <button onClick={() => onSetGroupLayers([...keys], true)} className="text-slate-400 hover:text-white">All</button>
            <button onClick={() => onSetGroupLayers([...keys], false)} className="text-slate-400 hover:text-white">None</button>
          </div>
        </div>
        {layerGroupOpen[groupKey] && (
          <div className="pl-4 pb-2 space-y-2">
            {checkboxes.map(function (cb) {
              return (
                <label key={cb.key} className="flex items-center gap-2.5 text-sm text-slate-300 cursor-pointer">
                  <input type="checkbox" checked={layers[cb.key]} onChange={() => onToggleLayer(cb.key)} className="accent-blue-500" />
                  {cb.label}
                </label>
              );
            })}
          </div>
        )}
      </div>
    );
  }

  return (
    <div className="border-b border-white/10">
      <button
        onClick={onToggleLayersOpen}
        className="w-full px-5 py-3 flex items-center justify-between text-xs font-semibold uppercase tracking-widest text-slate-300 hover:text-white"
      >
        Data Layers
        <span>{layersOpen ? "\u2212" : "+"}</span>
      </button>
      {layersOpen && (
        <div className="px-5 pb-4 space-y-1">
          {renderGroup("infrastructure", "Infrastructure", LAYER_GROUPS.infrastructure, [
            { key: "powerPlants", label: "Power Plants (EIA-860)" },
            { key: "substations", label: "Substations (HIFLD)" },
            { key: "transmissionLines", label: "Transmission Lines (HIFLD)" },
            { key: "dataCenters", label: "Data Centers (OSM)" },
          ])}
          {renderGroup("capacity", "Capacity Signals", LAYER_GROUPS.capacity, [
            { key: "utilityTerritories", label: "Utility Territories (EIA)" },
            { key: "queueWithdrawals", label: "Queue Withdrawals (ISO)" },
          ])}
          {renderGroup("risk", "Site Risk", LAYER_GROUPS.risk, [
            { key: "floodZones", label: "Flood Zones (FEMA)" },
            { key: "brownfields", label: "Brownfield Sites (EPA)" },
          ])}
          {renderGroup("connectivity", "Connectivity", LAYER_GROUPS.connectivity, [
            { key: "broadband", label: "Broadband (FCC)" },
          ])}
        </div>
      )}
    </div>
  );
}
