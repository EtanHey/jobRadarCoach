"""Bound native Codex processes and their process groups on macOS/Linux."""
import os
import selectors
import signal
import subprocess
import time

from scraper.annotate import SUPPORTED_CODEX_CLI_VERSION


def _stop_group(process):
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    process.wait()


def run_codex_process(command, *, input, text, stdout, stderr, timeout, check, cwd, env):
    """Discard command output and kill remaining group members on every exit."""
    with subprocess.Popen(command, stdin=subprocess.PIPE, stdout=stdout, stderr=stderr,
                          text=text, cwd=cwd, env=env, start_new_session=True) as process:
        try:
            process.communicate(input=input, timeout=timeout)
            return subprocess.CompletedProcess(command, process.returncode)
        finally:
            _stop_group(process)


def _read_version(process, command, timeout):
    deadline = time.monotonic() + timeout
    output = bytearray()
    with selectors.DefaultSelector() as selector:
        selector.register(process.stdout, selectors.EVENT_READ)
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not selector.select(remaining):
                raise subprocess.TimeoutExpired(command, timeout)
            chunk = os.read(process.stdout.fileno(), 1025 - len(output))
            if not chunk:
                break
            output.extend(chunk)
            if len(output) > 1024:
                raise RuntimeError("Codex exceeded bounded version output")
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise subprocess.TimeoutExpired(command, timeout)
    process.wait(timeout=remaining)
    return bytes(output)


def verify_codex_version(codex, *, cwd, env, timeout):
    command = [codex, '--version']
    with subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                          stderr=subprocess.DEVNULL, cwd=cwd, env=env,
                          start_new_session=True) as process:
        try:
            output = _read_version(process, command, timeout)
            if process.returncode != 0 or output.strip() != SUPPORTED_CODEX_CLI_VERSION.encode():
                raise RuntimeError("Codex version is unsupported")
        finally:
            _stop_group(process)
