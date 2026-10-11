import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import fiberCut from "./__fixtures__/fiber-cut.json";
import stadium from "./__fixtures__/stadium-event.json";

interface Schema {
  $ref?: string;
  required?: string[];
  properties?: Record<string, Schema>;
  items?: Schema;
  discriminator?: { mapping?: Record<string, string> };
}

const openapi = JSON.parse(
  readFileSync(resolve(__dirname, "../../../docs/api/openapi.json"), "utf8"),
) as { components: { schemas: Record<string, Schema> } };
const schemas = openapi.components.schemas;

const nameOf = (ref: string) => ref.split("/").pop()!;

/** Required fields the schema names but the value lacks, following object references. */
function missing(schema: Schema, value: Record<string, unknown>): string[] {
  const resolved = schema.$ref ? schemas[nameOf(schema.$ref)] : schema;
  const out = (resolved.required ?? []).filter((k) => !(k in value));
  for (const [key, prop] of Object.entries(resolved.properties ?? {})) {
    const child = value[key];
    if (prop.$ref && child && typeof child === "object" && !Array.isArray(child)) {
      out.push(...missing(prop, child as Record<string, unknown>).map((m) => `${key}.${m}`));
    }
  }
  return out;
}

describe.each([
  ["fiber-cut", fiberCut],
  ["stadium-event", stadium],
])("recording %s against the API contract", (_, recording) => {
  const mapping = schemas.Recording.properties!.events.items!.discriminator!.mapping!;

  it("has the metadata the contract requires", () => {
    expect(missing({ $ref: "#/components/schemas/Recording" }, recording as never)).toEqual([]);
  });

  it("has events whose envelope and data carry every required field", () => {
    expect(recording.events.length).toBeGreaterThan(10);
    recording.events.forEach((event, i) => {
      const target = mapping[event.type];
      expect(target, `unknown event type ${event.type}`).toBeDefined();
      expect(event.seq).toBe(i);
      expect(missing({ $ref: target }, event as never), `event ${i} (${event.type})`).toEqual([]);
    });
  });
});
