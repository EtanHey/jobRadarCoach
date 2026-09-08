# Foreground process ownership

The launcher creates each owned service with `start_new_session=True`. Its PID,
process group, session ID and OS start time identify that owned session. Command
text is diagnostic: fork and exec do not transfer ownership to somebody else.
A live matching leader authorizes group shutdown. If the leader exits, at least
one recorded descendant must retain its PID, session and start time before the
launcher signals the group. No surviving identity means fail closed and retain
state for inspection. New siblings and changed commands in the anchored group
remain owned. Existing borrowed services are separately checked against strict
command shapes and are never signaled by the launcher.

Commands must remain in the foreground and keep children in their process group.
A child that deliberately escapes with setsid/setpgid is outside this cleanup
contract. The portable ps start value has second resolution, and checking identity
then signaling is not atomic; this is accidental-process-reuse protection, not a
security boundary against a hostile local process. A stable wrapper leader or
platform-specific process handles would provide stronger guarantees.
