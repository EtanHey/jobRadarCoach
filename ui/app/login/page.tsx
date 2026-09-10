import { AuthShell } from "../../components/auth/auth-shell";
import { AuthSystemTheme } from "../../components/auth/auth-system-theme";
import { LoginForm } from "../../components/auth/login-form";
import { readOwnerAuthConfig } from "../../lib/auth/boundary";
import { readRecoveryConfig, safeNextPath } from "../../lib/auth/flow";

export const dynamic = "force-dynamic";

export default async function LoginPage({
  searchParams,
}: {
  searchParams: Promise<{ next?: string; error?: string }>;
}) {
  const query = await searchParams;
  const configured = readOwnerAuthConfig(process.env);
  return (
    <AuthShell title="Private sign in">
      <AuthSystemTheme />
      {configured.ok ? (
        <LoginForm
          supabaseUrl={configured.value.supabaseUrl}
          publishableKey={configured.value.publishableKey}
          nextPath={safeNextPath(query.next)}
          recoveryEnabled={readRecoveryConfig(process.env).ok}
        />
      ) : (
        <p role="alert" className="text-sm leading-6 text-muted-foreground">
          Authentication is not configured. This workspace remains closed.
        </p>
      )}
      {query.error ? (
        <p role="alert" className="mt-4 text-sm text-destructive">The sign-in link could not be accepted.</p>
      ) : null}
    </AuthShell>
  );
}
