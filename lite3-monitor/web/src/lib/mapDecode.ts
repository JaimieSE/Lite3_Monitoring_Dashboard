import type { DecodedMap, MapMsg } from "./types";

/** Inflate the bridge's zlib+base64 occupancy grid using the browser's native DecompressionStream. */
export async function decodeMap(msg: MapMsg): Promise<DecodedMap> {
  const bin = atob(msg.data);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  const stream = new Blob([bytes]).stream().pipeThrough(new DecompressionStream("deflate"));
  const cells = new Uint8Array(await new Response(stream).arrayBuffer());
  if (cells.length !== msg.width * msg.height) {
    throw new Error(`map size mismatch: ${cells.length} != ${msg.width}x${msg.height}`);
  }
  return {
    version: msg.version,
    frame: msg.frame,
    resolution: msg.resolution,
    width: msg.width,
    height: msg.height,
    origin: msg.origin,
    cells,
    stats: msg.stats,
    receivedAt: Date.now(),
  };
}
