"use client";

import Link from "next/link";
import { useEffect, useRef } from "react";

import { ThemeToggle } from "@/components/theme-toggle";
import { transcriptIsSpeaking } from "@/lib/voice/activity";
import { useVoiceSession } from "./use-voice-session";

const micMessages = {
  claim_failed: "The microphone could not be reserved. Try again.",
  ownership_lost: "Another browser took the microphone. It is closed here.",
  capture_failed: "Microphone access failed. Allow microphone permission, then try again.",
  release_failed: "The microphone is stopped, but its reservation could not be released.",
  stream_lost: "Microphone coordination was interrupted. Reconnect before trying again.",
} as const;

function MicGlyph({ open }: { open: boolean }) {
  return open ? (
    <svg aria-hidden="true" viewBox="0 0 24 24" className="size-8 fill-none stroke-current stroke-2">
      <path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Z" />
      <path d="M5 10v2a7 7 0 0 0 14 0v-2M12 19v3M8 22h8" />
    </svg>
  ) : (
    <svg aria-hidden="true" viewBox="0 0 24 24" className="size-8 fill-none stroke-current stroke-2">
      <path d="m2 2 20 20M9 9v3a3 3 0 0 0 5.1 2.1M15 9.3V5a3 3 0 0 0-5.6-1.5M5 10v2a7 7 0 0 0 12 4.9M19 10v2a7 7 0 0 1-.3 2M12 19v3M8 22h8" />
    </svg>
  );
}

export function VoicePage() {
  const {
    qa, roomPhase, mic, transcript, agentIdentity, agentConnected, agentResponsive, activity, soundBlocked,
    error, applicationLink, audioHostRef, connect, disconnect, tapMic, enableSound,
    retryQaVerification,
  } = useVoiceSession();
  const feedRef = useRef<HTMLDivElement>(null);
  const nearBottomRef = useRef(true);
  const linkRef = useRef<HTMLAnchorElement>(null);
  const focusedRevisionRef = useRef(0);
  const connected = roomPhase === "connected";
  const qaBlocked = qa.status === "checking" || qa.status === "error";
  const micOpen = mic.phase === "open";

  useEffect(() => {
    if (!nearBottomRef.current) return;
    const frame = requestAnimationFrame(() => {
      const feed = feedRef.current;
      if (feed) feed.scrollTo({ top: feed.scrollHeight, behavior: "smooth" });
    });
    return () => cancelAnimationFrame(frame);
  }, [transcript]);

  useEffect(() => {
    const link = applicationLink;
    if (!link?.popupBlocked || focusedRevisionRef.current === link.revision) return;
    focusedRevisionRef.current = link.revision;
    const frame = requestAnimationFrame(() => {
      linkRef.current?.focus();
      linkRef.current?.scrollIntoView({ block: "nearest", behavior: "smooth" });
    });
    return () => cancelAnimationFrame(frame);
  }, [applicationLink]);

  const connectionText = roomPhase === "connecting" ? "Connecting to voice room…"
    : roomPhase === "reconnecting" ? "Reconnecting…"
      : connected && agentConnected && !agentResponsive ? "Voice agent not responding"
      : connected && agentConnected ? "Voice agent connected"
        : connected ? "Waiting for voice agent"
          : roomPhase === "disconnected" ? "Voice room disconnected"
            : "Voice room disconnected";
  const micText = mic.phase === "opening" ? "Opening"
    : mic.phase === "open" ? "Open"
      : mic.phase === "error" ? "Error" : "Closed";

  return (
    <main className="flex h-dvh min-h-0 flex-col overflow-hidden bg-background text-foreground"
      data-room-phase={roomPhase} data-mic-phase={mic.phase}
      data-agent-connected={agentConnected} data-agent-responsive={agentResponsive} data-agent-activity={activity} data-qa-status={qa.status}>
      {qa.mode && (
        <div role={qa.status === "error" ? "alert" : "status"}
          className={`px-4 py-2 text-center text-sm font-bold tracking-wide ${qa.status === "ready"
            ? "bg-amber-400 text-black" : "bg-red-600 text-white"}`}>
          {qa.status === "ready" ? "QA MODE · READ ONLY · SERVER VERIFIED"
            : qa.status === "checking" ? "QA MODE · VERIFYING READ-ONLY BOUNDARY…"
              : "QA NOT READY · CONNECT DISABLED"}
        </div>
      )}

      <header className="flex items-center justify-between gap-4 border-b bg-card/80 px-4 py-3 backdrop-blur sm:px-6">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span className={`size-2.5 rounded-full ${connected && agentResponsive ? "bg-emerald-500" : connected ? "bg-amber-500" : "bg-muted-foreground/50"}`} />
            <h1 className="truncate text-lg font-semibold">Voice job coach</h1>
          </div>
          <p className="mt-0.5 text-xs text-muted-foreground">Automatic dispatch · {connectionText}</p>
          {agentConnected && agentIdentity && (
            <p className="truncate text-xs text-muted-foreground">Agent: {agentIdentity}</p>
          )}
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <ThemeToggle />
          <button type="button" disabled={roomPhase === "connecting" || qaBlocked}
            onClick={() => connected || roomPhase === "reconnecting" ? disconnect() : void connect()}
            className="h-9 rounded-xl border bg-card px-3 text-sm font-medium transition hover:bg-muted focus-visible:outline-2 focus-visible:outline-offset-2 disabled:opacity-50">
            {connected || roomPhase === "reconnecting" ? "Disconnect"
              : roomPhase === "connecting" ? "Connecting…" : "Connect"}
          </button>
        </div>
      </header>

      <div ref={feedRef} role="log" aria-label="Voice conversation" aria-live="polite"
        onScroll={(event) => {
          const feed = event.currentTarget;
          nearBottomRef.current = feed.scrollHeight - feed.scrollTop - feed.clientHeight < 96;
        }}
        className="min-h-0 flex-1 overflow-y-auto px-4 py-5 sm:px-6">
        <div className="mx-auto flex w-full max-w-3xl flex-col gap-3">
          {transcript.length === 0 ? (
            <section className="mt-[12vh] rounded-3xl border bg-card p-6 text-center shadow-sm">
              <h2 className="text-xl font-semibold">Talk through your job search</h2>
              <p className="mx-auto mt-2 max-w-md text-sm leading-6 text-muted-foreground">
                Connect to a private voice room. Then tap the microphone when you want to speak.
                Connecting alone never starts capture.
              </p>
              {connected && !agentConnected && (
                <p className="mt-4 rounded-xl bg-muted px-3 py-2 text-sm">Waiting for a voice agent to join this room…</p>
              )}
            </section>
          ) : transcript.map((segment) => (
            <article key={`${segment.senderIdentity}:${segment.segmentId}`}
              className={`max-w-[88%] rounded-2xl border px-4 py-3 shadow-sm ${segment.role === "user"
                ? "ml-auto bg-primary text-primary-foreground" : "mr-auto bg-card"}`}>
              <p className={`mb-1 text-[0.68rem] font-semibold uppercase tracking-wider ${segment.role === "user"
                ? "text-primary-foreground/70" : "text-muted-foreground"}`}>
                {segment.role === "user" ? "You" : "Voice agent"}
              </p>
              <p className="whitespace-pre-wrap text-sm leading-6">{segment.text}</p>
              {transcriptIsSpeaking(segment, activity) && <span className="mt-1 block text-xs opacity-65">Speaking…</span>}
            </article>
          ))}

          {applicationLink && (
            <section className="rounded-2xl border border-primary/30 bg-card p-4 shadow-sm"
              data-grounded-application={applicationLink.href}>
              <p className="text-sm font-semibold">Application link</p>
              <p className="mt-1 text-xs text-muted-foreground">
                Verified for this job.
              </p>
              <a ref={linkRef} href={applicationLink.href} target="_blank" rel="noopener noreferrer"
                className="mt-3 inline-flex rounded-xl bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground outline-none focus-visible:ring-3 focus-visible:ring-ring/50">
                Open application
              </a>
              <p className="mt-2 text-sm" role="status" aria-live="assertive">
                {applicationLink.popupBlocked ? "A new tab could not be confirmed. Tap the link above."
                  : "The verified application link remains available here."}
              </p>
            </section>
          )}
        </div>
      </div>

      <footer className="sticky bottom-0 border-t bg-background/95 px-4 pb-[max(1rem,env(safe-area-inset-bottom))] pt-3 backdrop-blur sm:px-6">
        <div className="mx-auto flex max-w-3xl items-center justify-between gap-3">
          <div className="min-w-0 flex-1" aria-live="polite">
            <p className="text-sm font-semibold">{connected && agentConnected && agentResponsive && micOpen
              ? activity === "speaking" ? "Speaking" : activity === "thinking" ? "Thinking" : activity === "listening" ? "Listening" : "Microphone open"
              : `Microphone: ${micText}`}</p>
            <p className="text-xs leading-5 text-muted-foreground">
              {mic.error ? micMessages[mic.error]
                : !connected ? "Connect before opening the microphone."
                  : !mic.ready ? "Waiting for microphone coordination…"
                    : micOpen ? "Tap to close." : "Tap when you want to speak."}
            </p>
          </div>
          <button type="button" aria-label={micOpen ? "Close microphone" : "Open microphone"}
            aria-pressed={micOpen} aria-busy={mic.phase === "opening"} disabled={!connected || !agentConnected || !agentResponsive || (!mic.ready && mic.phase !== "open" && mic.phase !== "opening")}
            onClick={tapMic}
            className={`grid size-16 shrink-0 place-items-center rounded-full border-4 shadow-lg transition focus-visible:outline-2 focus-visible:outline-offset-4 disabled:opacity-40 ${
              micOpen ? "border-red-300 bg-red-600 text-white" : mic.phase === "opening"
                ? "animate-pulse border-amber-200 bg-amber-500 text-black" : "border-primary/25 bg-primary text-primary-foreground"
            }`}>
            <MicGlyph open={micOpen || mic.phase === "opening"} />
          </button>
        </div>
        {(error || qa.status === "error") && (
          <div role="alert" className="mx-auto mt-2 flex max-w-3xl items-center justify-center gap-2 text-sm text-destructive">
            <p>{qa.status === "error" ? "QA NOT READY: the server did not attest this read-only session." : error}</p>
            {qa.status === "error" && qa.sessionId && (
              <button type="button" onClick={retryQaVerification}
                className="shrink-0 rounded-lg border border-destructive/40 px-2 py-1 font-medium hover:bg-destructive/10 focus-visible:outline-2 focus-visible:outline-offset-2">
                Retry QA verification
              </button>
            )}
          </div>
        )}
        {soundBlocked && (
          <button type="button" onClick={enableSound}
            className="mx-auto mt-2 block rounded-lg border px-3 py-1.5 text-sm font-medium hover:bg-muted focus-visible:outline-2 focus-visible:outline-offset-2">
            Enable sound
          </button>
        )}
        <Link href="/" className="mx-auto mt-2 block w-fit text-xs text-muted-foreground underline-offset-4 hover:underline">
          Back to job radar
        </Link>
      </footer>
      <div ref={audioHostRef} aria-hidden="true" />
    </main>
  );
}
