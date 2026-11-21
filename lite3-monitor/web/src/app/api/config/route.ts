import { NextResponse } from "next/server";
import type { DashboardConfig } from "@/lib/types";

export const dynamic = "force-dynamic";

/** Runtime dashboard configuration (read from env at request time - no rebuild needed). */
export async function GET() {
  const dom = process.env.LITE3_EXPECTED_DOMAIN_ID;
  const cfg: DashboardConfig = {
    bridgeUrl: process.env.LITE3_BRIDGE_WS_URL || "ws://127.0.0.1:8765/ws",
    expectedHostname: process.env.LITE3_EXPECTED_HOSTNAME || null,
    expectedDomainId: dom && dom.trim() !== "" && !Number.isNaN(Number(dom)) ? Number(dom) : null,
  };
  return NextResponse.json(cfg);
}
