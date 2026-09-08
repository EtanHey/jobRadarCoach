export interface VoiceCaptureTrack {
  mediaStreamTrack: { stop(): void };
}

export interface VoiceCaptureSession {
  createTrack(): Promise<VoiceCaptureTrack>;
  publish(track: VoiceCaptureTrack): Promise<unknown>;
  unpublish(track: VoiceCaptureTrack): Promise<unknown>;
}

export function createGuardedCaptureAdapter(
  getSession: () => VoiceCaptureSession | null,
) {
  let generation = 0;
  const active = new Map<VoiceCaptureTrack, VoiceCaptureSession>();

  const stopTrack = (track: VoiceCaptureTrack, session: VoiceCaptureSession) => {
    if (!active.delete(track)) return false;
    track.mediaStreamTrack.stop();
    void session.unpublish(track).catch(() => undefined);
    return true;
  };

  return {
    async enable() {
      const attempt = generation;
      const session = getSession();
      if (!session) throw new Error("Voice room is not connected.");
      const track = await session.createTrack();
      active.set(track, session);
      if (attempt !== generation || session !== getSession()) {
        stopTrack(track, session);
        throw new Error("Voice session changed during microphone capture.");
      }
      try {
        await session.publish(track);
      } catch (error) {
        stopTrack(track, session);
        throw error;
      }
      if (attempt !== generation || session !== getSession()) {
        if (!stopTrack(track, session)) void session.unpublish(track).catch(() => undefined);
        throw new Error("Voice session changed during microphone publication.");
      }
      let stopped = false;
      return {
        stop() {
          if (stopped) return;
          stopped = true;
          stopTrack(track, session);
        },
      };
    },
    stop() {
      generation += 1;
      for (const [track, session] of [...active]) stopTrack(track, session);
    },
  };
}
