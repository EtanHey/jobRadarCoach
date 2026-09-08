"use client";

import {
  createLocalAudioTrack, ParticipantKind, Room, RoomEvent, Track,
  type LocalAudioTrack, type RemoteParticipant, type RemoteTrack, type RpcInvocationData,
} from "livekit-client";
import { useCallback, useEffect, useRef, useState } from "react";
import { flushSync } from "react-dom";
import { z } from "zod";

import {
  createOpenJobRpcHandler, OPEN_JOB_RPC_METHOD, OpenJobProtocolError,
  reduceTranscript, TRANSCRIPTION_TOPIC, type TranscriptRole, type TranscriptSegment,
} from "@/lib/voice/client-protocol";
import { createMicClient, type MicClientState } from "@/lib/voice/mic-client";
import { createGuardedCaptureAdapter, type VoiceCaptureSession } from "./capture-adapter";

const qaSession = z.uuid();
const qaPreflight = z.object({
  version: z.literal(1), qa_mode: z.literal(true), session_id: qaSession,
  browser_mutations_blocked: z.literal(true), mic_isolated: z.literal(true),
  agent_qa_verified: z.literal(true), dispatch_mode: z.literal("automatic"),
}).strict();
const tokenBase = z.object({
  server_url: z.string().min(1), token: z.string().min(1), room_name: z.string().min(1),
  participant_identity: z.string().min(1), dispatch_mode: z.literal("automatic"),
});
const normalToken = tokenBase.strict();
const qaToken = tokenBase.extend({
  qa: z.object({ version: z.literal(1), session_id: qaSession, read_only: z.literal(true) }).strict(),
}).strict();

export type VoiceRoomPhase = "idle" | "connecting" | "connected" | "reconnecting" | "disconnected" | "error";
export interface GroundedApplicationLink { href: string; popupBlocked: boolean; revision: number }
export interface VoiceQaState {
  mode: boolean;
  status: "checking" | "off" | "ready" | "error";
  sessionId: string | null;
}

const initialMic: MicClientState = {
  phase: "closed", ready: false, owner: null, revision: null, error: null,
};
const qaBoundaryFailures = new Set<MicClientState["error"]>([
  "claim_failed", "release_failed", "stream_lost",
]);

export function handleMicStateForSession(
  next: MicClientState,
  effects: {
    qaMode: boolean;
    isCurrent(): boolean;
    publish(state: MicClientState): void;
    closeSession(): void;
    revokeQa(): void;
  },
) {
  if (!effects.isCurrent()) return;
  effects.publish(next);
  if (!effects.qaMode || !qaBoundaryFailures.has(next.error)) return;
  queueMicrotask(() => {
    if (!effects.isCurrent()) return;
    effects.closeSession();
    effects.revokeQa();
  });
}

interface TranscriptReader extends AsyncIterable<string> {
  info: { topic: string; id: string; attributes?: Record<string, string> };
}

export async function readTranscriptStream(
  reader: TranscriptReader,
  isCurrent: () => boolean,
  receive: (text: string, chunkIndex: number, attributes: Record<string, string>) => void,
) {
  let chunkIndex = 0;
  for await (const text of reader) {
    if (!isCurrent()) return;
    receive(text, chunkIndex++, reader.info.attributes ?? {});
  }
  if (chunkIndex > 0 && isCurrent()
      && reader.info.attributes?.["lk.transcription_final"] === "true") {
    receive("", chunkIndex, reader.info.attributes);
  }
}

export function useVoiceSession() {
  const [clientId] = useState(() => crypto.randomUUID());
  const [qa, setQa] = useState<VoiceQaState>({ mode: false, status: "checking", sessionId: null });
  const [qaAttempt, setQaAttempt] = useState(0);
  const [roomPhase, setRoomPhase] = useState<VoiceRoomPhase>("idle");
  const [mic, setMic] = useState<MicClientState>(initialMic);
  const [transcript, setTranscript] = useState<readonly TranscriptSegment[]>([]);
  const [agentIdentity, setAgentIdentity] = useState<string | null>(null);
  const [agentConnected, setAgentConnected] = useState(false);
  const [soundBlocked, setSoundBlocked] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [applicationLink, setApplicationLink] = useState<GroundedApplicationLink | null>(null);
  const audioHostRef = useRef<HTMLDivElement>(null);
  const generationRef = useRef(0);
  const pendingAbortRef = useRef<AbortController | null>(null);
  const captureSessionRef = useRef<VoiceCaptureSession | null>(null);
  const sessionRef = useRef<{
    room: Room; abort: AbortController; mic: ReturnType<typeof createMicClient> | null;
    audio: Map<RemoteTrack, HTMLMediaElement>; manual: boolean;
  } | null>(null);

  const clearAudio = useCallback(() => {
    const session = sessionRef.current;
    if (!session) return;
    for (const [track, element] of session.audio) {
      track.detach(element);
      element.remove();
    }
    session.audio.clear();
  }, []);

  const closeSession = useCallback((update = true) => {
    generationRef.current += 1;
    pendingAbortRef.current?.abort();
    pendingAbortRef.current = null;
    captureSessionRef.current = null;
    const session = sessionRef.current;
    sessionRef.current = null;
    if (session) {
      session.manual = true;
      session.abort.abort();
      session.mic?.dispose();
      for (const [track, element] of session.audio) { track.detach(element); element.remove(); }
      session.audio.clear();
      void session.room.disconnect(true);
    }
    if (update) {
      setMic(initialMic); setRoomPhase("idle"); setAgentConnected(false);
      setAgentIdentity(null); setSoundBlocked(false); setError(null);
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    const params = new URLSearchParams(window.location.search);
    if (!params.has("qa")) {
      queueMicrotask(() => { if (!controller.signal.aborted) setQa({ mode: false, status: "off", sessionId: null }); });
      return () => controller.abort();
    }
    const parsed = qaSession.safeParse(params.get("qa"));
    if (!parsed.success) {
      queueMicrotask(() => { if (!controller.signal.aborted) setQa({ mode: true, status: "error", sessionId: null }); });
      return () => controller.abort();
    }
    queueMicrotask(() => {
      if (!controller.signal.aborted) setQa({ mode: true, status: "checking", sessionId: parsed.data });
    });
    void fetch("/api/livekit/qa", { method: "GET", cache: "no-store", signal: controller.signal })
      .then(async (response) => {
        if (!response.ok) throw new Error();
        const proof = qaPreflight.parse(await response.json());
        if (proof.session_id !== parsed.data) throw new Error();
        setQa({ mode: true, status: "ready", sessionId: parsed.data });
      })
      .catch(() => { if (!controller.signal.aborted) setQa({ mode: true, status: "error", sessionId: parsed.data }); });
    return () => controller.abort();
  }, [qaAttempt]);

  useEffect(() => {
    const leave = () => closeSession(false);
    window.addEventListener("pagehide", leave);
    return () => { window.removeEventListener("pagehide", leave); closeSession(false); };
  }, [closeSession]);

  const connect = useCallback(async () => {
    if (qa.status === "checking" || qa.status === "error") return;
    closeSession();
    const generation = generationRef.current;
    const abort = new AbortController();
    pendingAbortRef.current = abort;
    setRoomPhase("connecting"); setError(null); setTranscript([]); setApplicationLink(null);
    try {
      const headers: Record<string, string> = { "content-type": "application/json" };
      if (qa.mode && qa.sessionId) headers["X-Voice-QA-Session"] = qa.sessionId;
      const response = await fetch("/api/livekit/token", {
        method: "POST", headers, body: JSON.stringify({ client_id: clientId }), signal: abort.signal,
      });
      if (!response.ok) throw new Error("token");
      const raw: unknown = await response.json();
      let token: z.infer<typeof normalToken>;
      if (qa.mode) {
        const attested = qaToken.parse(raw);
        if (!qa.sessionId || attested.qa.session_id !== qa.sessionId) throw new Error("qa");
        token = attested;
      } else token = normalToken.parse(raw);
      if (generation !== generationRef.current) return;

      const room = new Room({ adaptiveStream: true, dynacast: true });
      const audio = new Map<RemoteTrack, HTMLMediaElement>();
      const session: NonNullable<typeof sessionRef.current> = {
        room, abort, mic: null, audio, manual: false,
      };
      pendingAbortRef.current = null;
      sessionRef.current = session;
      let pinnedAgent: string | null = null;
      let rpcHandler: ReturnType<typeof createOpenJobRpcHandler> | null = null;
      const isCurrent = () => generation === generationRef.current && sessionRef.current === session;
      const pinAgent = (participant: RemoteParticipant) => {
        if (participant.kind !== ParticipantKind.AGENT) return false;
        if (pinnedAgent === null) { pinnedAgent = participant.identity; setAgentIdentity(participant.identity); }
        if (pinnedAgent !== participant.identity) return false;
        setAgentConnected(true); return true;
      };
      const captureSession: VoiceCaptureSession = {
        createTrack: () => createLocalAudioTrack(),
        publish: (track) => room.localParticipant.publishTrack(track as LocalAudioTrack, { source: Track.Source.Microphone }),
        unpublish: (track) => room.localParticipant.unpublishTrack(track as LocalAudioTrack, false),
      };
      captureSessionRef.current = captureSession;
      const capture = createGuardedCaptureAdapter(() => isCurrent() ? captureSessionRef.current : null);

      room.registerTextStreamHandler(TRANSCRIPTION_TOPIC, (reader, participantInfo) => {
        const participant = room.remoteParticipants.get(participantInfo.identity);
        const role: TranscriptRole = participantInfo.identity === room.localParticipant.identity ? "user" : "agent";
        if (role === "agent" && (!participant || !pinAgent(participant))) return;
        void readTranscriptStream(reader, isCurrent, (text, chunkIndex, attributes) => {
          setTranscript((current) => reduceTranscript(current, {
            topic: reader.info.topic, senderIdentity: participantInfo.identity, role,
            streamId: reader.info.id, chunkIndex, text, attributes,
          }));
        }).catch(() => { if (isCurrent()) setError("The live transcript was interrupted."); });
      });
      room.registerRpcMethod(OPEN_JOB_RPC_METHOD, async (data: RpcInvocationData) => {
        if (!isCurrent() || abort.signal.aborted) throw new OpenJobProtocolError();
        const participant = room.remoteParticipants.get(data.callerIdentity);
        if (!participant || !pinAgent(participant)) throw new OpenJobProtocolError();
        rpcHandler ??= createOpenJobRpcHandler({
          trustedAgentIdentity: participant.identity,
          fetchJob: (input, init) => fetch(input, { ...init,
            signal: init?.signal ? AbortSignal.any([abort.signal, init.signal]) : abort.signal,
          }),
          openWindow: (url, target, features) => {
            if (!isCurrent() || abort.signal.aborted) throw new OpenJobProtocolError();
            flushSync(() => setApplicationLink((current) => ({
              href: url, popupBlocked: false, revision: (current?.revision ?? 0) + 1,
            })));
            return window.open(url, target, features);
          },
          renderFallback: ({ href }) => {
            if (!isCurrent() || abort.signal.aborted) throw new OpenJobProtocolError();
            flushSync(() => setApplicationLink((current) => ({
              href, popupBlocked: true, revision: (current?.revision ?? 0) + 1,
            })));
          },
        });
        return rpcHandler({ callerIdentity: data.callerIdentity, payload: data.payload });
      });
      room.on(RoomEvent.ParticipantConnected, pinAgent);
      room.on(RoomEvent.ParticipantDisconnected, (participant) => {
        if (participant.identity === pinnedAgent) setAgentConnected(false);
      });
      room.on(RoomEvent.TrackSubscribed, (track) => {
        if (track.kind !== Track.Kind.Audio || !isCurrent()) return;
        const element = track.attach(); element.autoplay = true; element.hidden = true;
        audio.set(track, element); audioHostRef.current?.append(element);
      });
      room.on(RoomEvent.TrackUnsubscribed, (track) => {
        const element = audio.get(track); if (!element) return;
        track.detach(element); element.remove(); audio.delete(track);
      });
      room.on(RoomEvent.AudioPlaybackStatusChanged, (playing) => setSoundBlocked(!playing));
      room.on(RoomEvent.Reconnecting, () => {
        if (!isCurrent()) return;
        void session.mic?.suspend(); setRoomPhase("reconnecting");
        setError("Connection interrupted. Microphone closed; tap again after reconnecting.");
      });
      room.on(RoomEvent.Reconnected, () => {
        if (!isCurrent()) return;
        setRoomPhase("connected"); setError("Reconnected. Tap the microphone when you are ready.");
      });
      room.on(RoomEvent.Disconnected, () => {
        if (!isCurrent() || session.manual) return;
        captureSessionRef.current = null; void session.mic?.suspend(); clearAudio();
        setRoomPhase("disconnected"); setAgentConnected(false);
        setError("Voice room disconnected. Connect again to continue.");
      });
      await room.connect(token.server_url, token.token);
      if (!isCurrent()) { void room.disconnect(true); return; }
      room.remoteParticipants.forEach(pinAgent);
      session.mic = createMicClient({ clientId, capture });
      session.mic.subscribe((next) => handleMicStateForSession(next, {
        qaMode: qa.mode,
        isCurrent,
        publish: setMic,
        closeSession: () => closeSession(),
        revokeQa: () => {
          setQa((current) => ({ ...current, status: "error" }));
          setRoomPhase("error");
          setError("QA voice session verification was lost. Recheck before connecting again.");
        },
      }));
      setMic(session.mic.getState()); setRoomPhase("connected");
      setSoundBlocked(!room.canPlaybackAudio); void room.startAudio().catch(() => setSoundBlocked(true));
    } catch {
      if (abort.signal.aborted) return;
      closeSession(false); setRoomPhase("error");
      if (qa.mode) setQa((current) => ({ ...current, status: "error" }));
      setError(qa.mode ? "QA voice session is not verified or available." : "Voice room is unavailable. Try connecting again.");
    }
  }, [clearAudio, clientId, closeSession, qa]);

  const tapMic = useCallback(() => {
    const session = sessionRef.current;
    if (!session || roomPhase !== "connected") return;
    void session.room.startAudio().catch(() => setSoundBlocked(true));
    void session.mic?.tap();
  }, [roomPhase]);
  const enableSound = useCallback(() => {
    void sessionRef.current?.room.startAudio().then(() => setSoundBlocked(false)).catch(() => setSoundBlocked(true));
  }, []);
  const retryQaVerification = useCallback(() => setQaAttempt((current) => current + 1), []);

  return {
    clientId, qa, roomPhase, mic, transcript, agentIdentity, agentConnected, soundBlocked,
    error, applicationLink, audioHostRef, connect, disconnect: closeSession, tapMic, enableSound,
    retryQaVerification,
  };
}
