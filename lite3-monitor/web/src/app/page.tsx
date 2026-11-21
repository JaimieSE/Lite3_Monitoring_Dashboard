"use client";

import { MapView } from "@/components/MapView";
import { EventLog, ExplorationPanel, HealthPanel, LiveCharts, RobotPanel, TfDiagPanel } from "@/components/LivePanels";
import { Panel } from "@/components/ui";
import { useTelemetry } from "@/components/TelemetryProvider";

export default function LivePage() {
  const { client } = useTelemetry();
  return (
    <div className="flex flex-col gap-2">
      <div className="grid grid-cols-12 gap-2">
        <Panel
          title="Live SLAM map"
          right={<span className="text-2xs text-faint">frame {client.hello?.frames.map ?? "map"}</span>}
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
      <LiveCharts />
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
