import { describe, expect, it } from "vitest";
import { readSse, SseParser } from "./sse";

const frame = (event: string, data: string) => `event: ${event}\ndata: ${data}\n\n`;

describe("SseParser", () => {
  it("parses a frame", () => {
    const p = new SseParser();
    expect(p.push(frame("note", '{"a":1}'))).toEqual([{ event: "note", data: '{"a":1}' }]);
  });

  it("ignores comment lines and keep-alives", () => {
    const p = new SseParser();
    const out = p.push(`: open\n\n: keep-alive\n\n${frame("scope", "{}")}: keep-alive\n\n`);
    expect(out).toEqual([{ event: "scope", data: "{}" }]);
  });

  it("handles chunk boundaries inside a frame, a line and a field", () => {
    const whole = frame("tool_call", '{"x":"héllo"}') + frame("gate", "{}");
    for (let size = 1; size <= whole.length; size++) {
      const p = new SseParser();
      const out = [];
      for (let i = 0; i < whole.length; i += size) out.push(...p.push(whole.slice(i, i + size)));
      expect(out.map((m) => m.event)).toEqual(["tool_call", "gate"]);
      expect(out[0].data).toBe('{"x":"héllo"}');
    }
  });

  it("joins multi-line data with a newline", () => {
    const p = new SseParser();
    expect(p.push("event: x\ndata: one\ndata: two\ndata:three\n\n")).toEqual([
      { event: "x", data: "one\ntwo\nthree" },
    ]);
  });

  it("accepts CRLF and lone CR line ends, even when CRLF is split across chunks", () => {
    const p = new SseParser();
    const out = [
      ...p.push("event: a\r\ndata: 1\r"),
      ...p.push("\n\r"),
      ...p.push("\nevent: b\rdata: 2\r\r"),
      ...p.push("\n"),
    ];
    expect(out).toEqual([
      { event: "a", data: "1" },
      { event: "b", data: "2" },
    ]);
  });

  it("defaults the event name and skips frames without data", () => {
    const p = new SseParser();
    expect(p.push("data: hi\n\nevent: empty\n\nid: 4\n\n")).toEqual([
      { event: "message", data: "hi" },
    ]);
  });

  it("drops an unfinished frame at the end of the stream", () => {
    const p = new SseParser();
    p.push("event: a\ndata: 1\n");
    expect(p.flush()).toEqual([]);
  });
});

describe("readSse", () => {
  it("decodes multi-byte characters split across chunks", async () => {
    const bytes = new TextEncoder().encode(frame("note", '{"t":"é—ü"}'));
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        for (let i = 0; i < bytes.length; i += 3) controller.enqueue(bytes.slice(i, i + 3));
        controller.close();
      },
    });
    const out = [];
    for await (const m of readSse(body)) out.push(m);
    expect(out).toEqual([{ event: "note", data: '{"t":"é—ü"}' }]);
  });
});
