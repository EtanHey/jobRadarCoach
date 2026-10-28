import { spawn } from 'node:child_process';
import { writeFileSync } from 'node:fs';
import { constants } from 'node:os';

// Keep the waitable supervisor outside the runner's group. This works in shells
// without job control, and keeps the group alive across descendant reparenting.
process.on('SIGINT', () => {});
process.on('SIGTERM', () => {});
const runner = spawn(process.execPath, [process.argv[2]], {
  detached: true,
  stdio: 'inherit',
});
runner.on('error', error => { console.error(error); process.exitCode = 1; });
runner.on('exit', (code, signal) => {
  process.exitCode = code ?? 128 + constants.signals[signal];
});
if (runner.pid) writeFileSync(process.argv[3], String(runner.pid));
