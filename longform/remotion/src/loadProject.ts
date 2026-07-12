import { staticFile } from "remotion";
import type { Mapping } from "./types";

/**
 * Carrega o mapping.json staged em public/<slug>/mapping.json.
 * Funciona tanto no Studio (browser) quanto no render (Node) via fetch + staticFile.
 */
export async function loadMapping(slug: string): Promise<Mapping> {
  const url = staticFile(`${slug}/mapping.json`);
  const res = await fetch(url);
  if (!res.ok) {
    throw new Error(`mapping.json não encontrado para slug "${slug}" (public/${slug}/mapping.json)`);
  }
  return (await res.json()) as Mapping;
}
