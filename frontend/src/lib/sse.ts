/**
 * A small Server-Sent Events parser for `fetch` streams. `EventSource` cannot send a POST body,
 * so the stream is read by hand.
 */

export interface SseMessage {
  event: string;
  data: string;
}

/**
 * Incremental parser. Feed it text as it arrives (chunks may end anywhere, even inside a line or
 * between the two characters of a CRLF); it returns the messages completed by each chunk.
 */
export class SseParser {
  private pending = "";
  private event = "";
  private data: string[] = [];

  push(chunk: string): SseMessage[] {
    const text = this.pending + chunk;
    const out: SseMessage[] = [];
    // A trailing CR may be the first half of a CRLF; wait for the next chunk to know.
    const held = text.endsWith("\r") ? "\r" : "";
    const body = held ? text.slice(0, -1) : text;
    const lines = body.split(/\r\n|\n|\r/);
    this.pending = (lines.pop() ?? "") + held;
    for (const line of lines) {
      const message = this.line(line);
      if (message) out.push(message);
    }
    return out;
  }

  /** Call when the stream ends. A frame without its closing blank line is dropped, as in browsers. */
  flush(): SseMessage[] {
    const out: SseMessage[] = [];
    if (this.pending) {
      const message = this.line(this.pending.replace(/\r$/, ""));
      if (message) out.push(message);
    }
    this.pending = "";
    this.event = "";
    this.data = [];
    return out;
  }

  private line(line: string): SseMessage | null {
    if (line === "") {
      const message =
        this.data.length > 0
          ? { event: this.event || "message", data: this.data.join("\n") }
          : null;
      this.event = "";
      this.data = [];
      return message;
    }
    if (line.startsWith(":")) return null;
    const colon = line.indexOf(":");
    const field = colon === -1 ? line : line.slice(0, colon);
    let value = colon === -1 ? "" : line.slice(colon + 1);
    if (value.startsWith(" ")) value = value.slice(1);
    if (field === "event") this.event = value;
    else if (field === "data") this.data.push(value);
    return null;
  }
}

/** Yields the messages of a response body until it ends or the signal aborts. */
export async function* readSse(
  body: ReadableStream<Uint8Array>,
): AsyncGenerator<SseMessage> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  const parser = new SseParser();
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      yield* parser.push(decoder.decode(value, { stream: true }));
    }
    yield* parser.push(decoder.decode());
    yield* parser.flush();
  } finally {
    reader.releaseLock();
  }
}
