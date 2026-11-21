import type { Metadata } from "next";
import "./globals.css";
import { TelemetryProvider } from "@/components/TelemetryProvider";
import { TopBar } from "@/components/TopBar";

export const metadata: Metadata = {
  title: "Lite3 Mission Control",
  description: "Read-only monitoring dashboard for the DEEP Robotics Lite3",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen">
        <TelemetryProvider>
          <TopBar />
          <main className="mx-auto max-w-[1920px] px-3 pb-4 pt-2">{children}</main>
        </TelemetryProvider>
      </body>
    </html>
  );
}
