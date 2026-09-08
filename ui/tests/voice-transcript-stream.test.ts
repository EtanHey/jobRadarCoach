import assert from "node:assert/strict";
import { test } from "node:test";

import {
  DataPacket, DataStream_Chunk, DataStream_Header, DataStream_TextHeader,
  DataStream_Trailer, Encryption_Type,
} from "@livekit/protocol";

import { readTranscriptStream } from "../components/voice/use-voice-session";
import {
  reduceTranscript, TRANSCRIPTION_TOPIC, type TranscriptSegment,
} from "../lib/voice/client-protocol";

const sender = "agent-test";
const attributes = {
  "lk.segment_id": "segment-1",
  "lk.transcribed_track_id": "track-1",
  "lk.transcription_final": "false",
};

interface StreamManager {
  setConnected(connected: boolean): void;
  registerTextStreamHandler(
    topic: string,
    callback: (reader: Parameters<typeof readTranscriptStream>[0]) => void,
  ): void;
  handleDataStreamPacket(packet: DataPacket, encryptionType: Encryption_Type): void;
}

async function streamHarness() {
  const internalSdkPath = ["..", "node_modules", "livekit-client", "src", "room", "data-stream",
    "incoming", "IncomingDataStreamManager.ts"].join("/");
  const loaded = await import(internalSdkPath) as { default: unknown };
  const first = loaded.default;
  const candidate = typeof first === "function" ? first : (first as { default: unknown }).default;
  const Manager = candidate as new () => StreamManager;
  const manager = new Manager();
  manager.setConnected(true);
  const streamId = crypto.randomUUID();
  let current = true;
  let segments: readonly TranscriptSegment[] = [];
  let settle!: () => void;
  let fail!: (error: unknown) => void;
  const done = new Promise<void>((resolve, reject) => { settle = resolve; fail = reject; });
  manager.registerTextStreamHandler(TRANSCRIPTION_TOPIC, (reader) => {
    void readTranscriptStream(reader, () => current, (text, chunkIndex, nextAttributes) => {
      segments = reduceTranscript(segments, {
        topic: TRANSCRIPTION_TOPIC, senderIdentity: sender, role: "agent", streamId,
        chunkIndex, text, attributes: nextAttributes,
      });
    }).then(settle, fail);
  });
  manager.handleDataStreamPacket(new DataPacket({
    participantIdentity: sender,
    value: { case: "streamHeader", value: new DataStream_Header({
      streamId, topic: TRANSCRIPTION_TOPIC, mimeType: "text/plain", timestamp: BigInt(0),
      attributes, contentHeader: { case: "textHeader", value: new DataStream_TextHeader({}) },
    }) },
  }), Encryption_Type.NONE);
  return {
    done,
    segments: () => segments,
    expire: () => { current = false; },
    push(text: string, index = 0) {
      manager.handleDataStreamPacket(new DataPacket({
        participantIdentity: sender,
        value: { case: "streamChunk", value: new DataStream_Chunk({
          streamId, chunkIndex: BigInt(index), content: new TextEncoder().encode(text),
        }) },
      }), Encryption_Type.NONE);
    },
    close(finalValue?: "true" | "false", reason = "") {
      manager.handleDataStreamPacket(new DataPacket({
        participantIdentity: sender,
        value: { case: "streamTrailer", value: new DataStream_Trailer({
          streamId, reason, attributes: finalValue ? { "lk.transcription_final": finalValue } : {},
        }) },
      }), Encryption_Type.NONE);
    },
  };
}

test("a completed SDK stream seals trailer-final text without changing it", async () => {
  const stream = await streamHarness();
  stream.push("Complete answer");
  await new Promise((resolve) => setTimeout(resolve, 0));
  assert.equal(stream.segments()[0].final, false);
  stream.close("true");
  await stream.done;
  assert.deepEqual(stream.segments().map(({ text, final }) => ({ text, final })), [
    { text: "Complete answer", final: true },
  ]);
});

test("non-final, empty, and stale streams are never sealed", async () => {
  const interim = await streamHarness();
  interim.push("Still speaking"); interim.close("false"); await interim.done;
  assert.equal(interim.segments()[0].final, false);

  const empty = await streamHarness();
  empty.close("true"); await empty.done;
  assert.deepEqual(empty.segments(), []);

  const aborted = await streamHarness();
  aborted.push("Interrupted");
  await new Promise((resolve) => setTimeout(resolve, 0));
  aborted.close("true", "cancelled");
  await assert.rejects(aborted.done, /closed abnormally/);
  assert.equal(aborted.segments()[0].final, false);

  const stale = await streamHarness();
  stale.push("Old session");
  await new Promise((resolve) => setTimeout(resolve, 0));
  stale.expire(); stale.close("true"); await stale.done;
  assert.equal(stale.segments()[0].final, false);
});
