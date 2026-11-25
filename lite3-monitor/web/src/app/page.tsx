"use client";

import { MapView } from "@/components/MapView";
import {
  BodyPanel, ComputePanel, DataRatePanel, EventLog, ExplorationPanel, HealthPanel, LiveCharts, PeerPanel,
  RobotLogPanel, RobotPanel, TemperaturePanel, TfDiagPanel,
} from "@/components/LivePanels";
import { Panel } from "@/components/ui";
import { useTelemetry } from "@/components/TelemetryProvider";

export default function LivePage() {
  const { client } = useTelemetry();
  return (
    <div className="flex flex-col gap-2">
      <div className="grid grid-cols-12 gap-2">
        <Panel
          title={client.map ? "Live SLAM map" : "Live position (no map)"}
          right={
            <span className="text-2xs text-faint">
              frame {client.map ? (client.hello?.frames.map ?? "map") : (client.telemetry?.pose?.frame ?? "—")}
              {client.telemetry?.pose ? ` · pose via ${client.telemetry.pose.source}` : ""}
            </span>
          }
          className="col-span-12 h-[calc(100vh-112px)] min-h-[520px] lg:col-span-8"
        >
          <MapView />
        </Panel>
        <div className="col-span-12 flex min-h-0 flex-col gap-2 lg:col-span-4 lg:h-[calc(100vh-112px)] lg:min-h-[520px]">
          <RobotPanel />
          <ExplorationPanel />
          <TfDiagPanel className="flex-1" />
        </div>
      </div>
      <div className="grid grid-cols-12 gap-2">
        <div className="col-span-12 h-[420px] xl:col-span-6">
          <BodyPanel />
        </div>
        <div className="col-span-12 h-[420px] xl:col-span-6">
          <RobotLogPanel />
        </div>
      </div>
      <div className="min-h-[300px]">
        <TemperaturePanel />
      </div>
      <LiveCharts />
      <div className="grid grid-cols-12 gap-2">
        <div className="col-span-12 h-[360px] xl:col-span-5">
          <ComputePanel />
        </div>
        <div className="col-span-12 h-[360px] md:col-span-6 xl:col-span-4">
          <PeerPanel />
        </div>
        <div className="col-span-12 h-[360px] md:col-span-6 xl:col-span-3">
          <DataRatePanel />
        </div>
      </div>
      <div className="grid grid-cols-12 gap-2">
        <div className="col-span-12 h-[360px] xl:col-span-8">
          <HealthPanel />
        </div>
        <div className="col-span-12 h-[360px] xl:col-span-4">
          <EventLog />
        </div>
      </div>
    </div>
  );
}
