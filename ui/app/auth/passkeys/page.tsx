import { AuthShell } from "../../../components/auth/auth-shell";
import { readOwnerAuthConfig } from "../../../lib/auth/boundary";
import { PasskeyEnrollment } from "./passkey-enrollment";

export const dynamic = "force-dynamic";

export default function PasskeysPage() {
  const configured = readOwnerAuthConfig(process.env);
  return (
    <AuthShell title="Create owner passkey">
      {configured.ok ? (
        <PasskeyEnrollment
          supabaseUrl={configured.value.supabaseUrl}
          publishableKey={configured.value.publishableKey}
        />
      ) : (
        <p role="alert" className="text-sm text-muted-foreground">Authentication is unavailable.</p>
      )}
    </AuthShell>
  );
}
