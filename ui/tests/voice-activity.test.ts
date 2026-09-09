import assert from "node:assert/strict";
import { test } from "node:test";
import { agentActivity, settleTranscriptStreams, transcriptIsSpeaking } from "../lib/voice/activity";
import type { TranscriptSegment } from "../lib/voice/client-protocol";

const segment: TranscriptSegment = {
  senderIdentity: "agent-1", role: "agent", segmentId: "one", trackId: "track",
  streamId: "stream", lastChunkIndex: 0, text: "Let me check —", final: false,
};

test("barge-in clears Speaking from partial text without inventing final text", () => {
  assert.equal(transcriptIsSpeaking(segment, "speaking"), true);
  const stopped = settleTranscriptStreams([segment], "agent-1")[0];
  assert.equal(stopped.text, segment.text);
  assert.equal(stopped.final, false);
  assert.equal(transcriptIsSpeaking(stopped, "listening"), false);
  assert.equal(transcriptIsSpeaking(stopped, "speaking"), false, "old text stays stopped on the next turn");
});

test("closed stream settles only its sender and stream", () => {
  const other = { ...segment, senderIdentity: "agent-2" };
  const next = { ...segment, segmentId: "two", streamId: "next" };
  const result = settleTranscriptStreams([segment, other, next], "agent-1", "stream");
  assert.equal(result[1], other); assert.equal(result[2], next);
  assert.equal(transcriptIsSpeaking(result[0], "speaking"), false);
  assert.equal(transcriptIsSpeaking(result[2], "speaking"), true);
});

test("only the published speaking state can label an agent transcript Speaking", () => {
  for (const state of ["listening", "thinking", "initializing", "idle", "unknown"]) {
    assert.equal(transcriptIsSpeaking(segment, agentActivity({ "lk.agent.state": state })), false);
  }
  assert.equal(agentActivity({ "lk.agent.state": "speaking" }), "speaking");
  assert.equal(agentActivity({}), "unknown");
});

import { Room, RoomEvent, type RemoteParticipant } from "livekit-client";
import { observeAgentActivity } from "../lib/voice/activity";

test("SDK agent state and departure notify immediately; other and stale peers cannot", () => {
  const room = new Room();
  let current = true; let departed = 0;
  const states: string[] = [];
  const stop = observeAgentActivity(room, {
    isCurrent: () => current, identity: () => "agent-1",
    stateChanged: (state) => states.push(state), departed: () => { departed++; },
  });
  const peer = { identity: "agent-1", attributes: { "lk.agent.state": "listening" } } as unknown as RemoteParticipant;
  room.emit(RoomEvent.ParticipantAttributesChanged, { "lk.agent.state": "listening" }, peer);
  assert.deepEqual(states, ["listening"]);
  room.emit(RoomEvent.ParticipantDisconnected, { identity: "other" } as RemoteParticipant);
  assert.equal(departed, 0);
  room.emit(RoomEvent.ParticipantDisconnected, peer);
  assert.equal(departed, 1, "departure is synchronous, with no room timeout or poll");
  current = false;
  room.emit(RoomEvent.ParticipantDisconnected, peer);
  assert.equal(departed, 1);
  stop(); current = true;
  room.emit(RoomEvent.ParticipantDisconnected, peer);
  assert.equal(departed, 1);
});
