import { RoomEvent, type Participant, type RemoteParticipant, type Room } from "livekit-client";
import type { TranscriptSegment } from "./client-protocol";

export type AgentActivity = "unknown" | "initializing" | "idle" | "listening" | "thinking" | "speaking";
export function agentActivity(attributes: Record<string, string>): AgentActivity {
  const state = attributes["lk.agent.state"];
  return state === "initializing" || state === "idle" || state === "listening"
    || state === "thinking" || state === "speaking" ? state : "unknown";
}

// Stream completion and speech completion are different from final transcription.
export function settleTranscriptStreams(
  segments: readonly TranscriptSegment[], sender: string, streamId?: string,
): readonly TranscriptSegment[] {
  return segments.map((segment) => segment.senderIdentity === sender
    && (streamId === undefined || segment.streamId === streamId)
    ? { ...segment, streaming: false } : segment);
}

export function transcriptIsSpeaking(segment: TranscriptSegment, state: AgentActivity): boolean {
  return !segment.final && segment.streaming !== false && (segment.role === "user" || state === "speaking");
}

export function observeAgentActivity(room: Pick<Room, "on" | "off">, effects: {
  isCurrent(): boolean;
  identity(): string | null;
  stateChanged(state: AgentActivity): void;
  departed(): void;
}) {
  const attributes = (changed: Record<string, string>, participant: Participant) => {
    if (!effects.isCurrent() || participant.identity !== effects.identity()
        || !("lk.agent.state" in changed)) return;
    effects.stateChanged(agentActivity(participant.attributes));
  };
  const departed = (participant: RemoteParticipant) => {
    if (effects.isCurrent() && effects.identity() !== null
        && participant.identity === effects.identity()) effects.departed();
  };
  room.on(RoomEvent.ParticipantAttributesChanged, attributes);
  room.on(RoomEvent.ParticipantDisconnected, departed);
  return () => {
    room.off(RoomEvent.ParticipantAttributesChanged, attributes);
    room.off(RoomEvent.ParticipantDisconnected, departed);
  };
}
