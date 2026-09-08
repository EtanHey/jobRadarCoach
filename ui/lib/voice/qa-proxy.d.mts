export interface QaProxyOptions {
  upstream: string; key: string; secret: string; serverUrl: string; qaSessionId: string;
  verifyAgent?: () => Promise<boolean>; upstreamOrigin?: string; publicOrigin?: string; port?: number;
}
export interface QaProxyReceipt {
  session_id: string;
  rooms: Array<{ room_name: string; participant_identity: string; client_id: string; dispatch_mode: string }>;
  isolatedMicCalls: number; ownerMicCalls: number; mutationAttempts: number; revoked: boolean;
}
export function startQaProxy(options: QaProxyOptions): Promise<{
  origin: string; qaUrl: string; readonly rooms: QaProxyReceipt["rooms"]; receipt(): QaProxyReceipt; invalidateQa(): void; close(): Promise<void>;
}>;
