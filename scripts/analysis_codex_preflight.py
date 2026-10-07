"""Read-only install preflight: report the pin and cached standalone freshness."""
import argparse
import ast
import os
from pathlib import Path
import plistlib
import re
import selectors
import signal
import subprocess
import sys
import time


MAX_VERSION_BYTES = 1024
VERSION_TIMEOUT = 10


def _stop_group(process):
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    finally:
        process.wait()


def _probe_version(binary):
    command = [str(binary), '--version']
    deadline = time.monotonic() + VERSION_TIMEOUT
    output = bytearray()
    with subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                          stderr=subprocess.DEVNULL, start_new_session=True) as process:
        cleanup_started = False
        try:
            with selectors.DefaultSelector() as selector:
                selector.register(process.stdout, selectors.EVENT_READ)
                while selector.get_map():
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise subprocess.TimeoutExpired(command, VERSION_TIMEOUT)
                    for _key, _events in selector.select(min(remaining, 0.05)):
                        # One excess byte detects overflow without retaining it.
                        chunk = os.read(process.stdout.fileno(), MAX_VERSION_BYTES + 1 - len(output))
                        if len(output) + len(chunk) > MAX_VERSION_BYTES:
                            raise RuntimeError('pinned Codex exceeded bounded version output; installation refused')
                        if not chunk:
                            selector.unregister(process.stdout)
                        else:
                            output.extend(chunk)
                    if not cleanup_started and process.poll() is not None:
                        # A successful parent may leave descendants holding stdout open.
                        cleanup_started = True
                        _stop_group(process)
            process.wait(timeout=max(0, deadline - time.monotonic()))
            return subprocess.CompletedProcess(command, process.returncode, stdout=bytes(output))
        finally:
            if not cleanup_started:
                _stop_group(process)


def check_pin(binary, expected, standalone):
    releases = standalone / 'releases'
    versions = [p.name.split('-', 1)[0] for p in releases.glob('*')
                if re.fullmatch(r'\d+\.\d+\.\d+-[a-z0-9-]+', p.name)
                and (p / 'bin/codex').is_file() and os.access(p / 'bin/codex', os.X_OK)]
    latest = max(versions, key=lambda v: tuple(map(int, v.split('.'))), default='UNKNOWN')
    pin = expected.removeprefix('codex-cli ')
    print(f'CODEX_PIN required={pin} latest_standalone={latest} (locally cached)', flush=True)
    if not binary.is_file() or not os.access(binary, os.X_OK):
        raise RuntimeError('pinned Codex binary is missing or not executable; installation refused')
    try:
        result = _probe_version(binary)
    except (OSError, subprocess.TimeoutExpired):
        raise RuntimeError('pinned Codex version probe failed; installation refused') from None
    if result.returncode or result.stdout.strip() != expected.encode():
        raise RuntimeError('pinned Codex version does not match the source pin; installation refused')
    print(f'CODEX_PIN installed={pin} latest_standalone={latest}', flush=True)
    if latest == 'UNKNOWN':
        print('CODEX_PIN WARNING: standalone inventory unavailable; freshness UNKNOWN', file=sys.stderr)
    elif tuple(map(int, pin.split('.'))) < tuple(map(int, latest.split('.'))):
        print(f'CODEX_PIN STALE: pinned {pin}, latest cached standalone {latest}; review the pin before release', file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('sha')
    parser.add_argument('--repo', type=Path, default=Path(__file__).resolve().parents[2 if Path(__file__).parent.name == 'tools' else 1])
    for option in ('workspace', 'sandbox-root', 'artifact-dir', 'lock-timeout', 'wait-seconds'):
        parser.add_argument('--' + option)
    args = parser.parse_args()
    ref = 'origin/master' if args.sha == 'master' else args.sha
    if not re.fullmatch(r'[0-9a-f]{7,40}|origin/master', ref):
        raise RuntimeError('invalid install source revision')
    source = subprocess.run(['git', '-C', str(args.repo), 'show', ref + ':scraper/annotate.py'],
                            capture_output=True, timeout=10, check=True).stdout
    expected = next((ast.literal_eval(node.value) for node in ast.parse(source).body
                    if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and
                    t.id == 'SUPPORTED_CODEX_CLI_VERSION' for t in node.targets)), None)
    if not isinstance(expected, str) or not re.fullmatch(r'codex-cli \d+\.\d+\.\d+', expected):
        raise RuntimeError('source Codex pin is invalid')
    plist = Path.home() / 'Library/LaunchAgents/com.jobradarcoach.local-analysis.plist'
    binary = Path(plistlib.loads(plist.read_bytes())['EnvironmentVariables']['CODEX'])
    check_pin(binary, expected, Path.home() / '.codex/packages/standalone')


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        # Library exceptions and binary output may contain credentials. Never echo them.
        print('CODEX_PIN BLOCKED: ' + (str(error) if type(error) is RuntimeError else type(error).__name__), file=sys.stderr)
        sys.exit(1)
