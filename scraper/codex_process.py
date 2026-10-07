"""Bound native Codex processes and their process groups on macOS/Linux."""
import os
import re
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
    finally:
        process.wait()


MAX_STDERR_BYTES = 16_384


def _stderr_category(raw, truncated):
    # Drop a possibly partial first line after tail truncation.
    if truncated:
        raw = raw.partition(b"\n")[2]
    errors = re.findall(rb"(?mi)^ERROR: ([^\r\n]*)", raw)
    if errors:
        terminal = errors[-1].lower()
        for category, markers in (
            ("quota", (b"usage_limit_reached", b"insufficient_quota", b"429", b"rate limit")),
            ("auth", (b"401 unauthorized", b"invalid_api_key", b"authentication", b"token_expired")),
            ("model_access", (b"model_not_found", b"model is not supported", b"model does not exist")),
        ):
            if any(marker in terminal for marker in markers):
                return category
    return "nonzero_exit"


def _bounded_stderr(process, command, stdin_text, timeout, stop_group):
    deadline = time.monotonic() + timeout
    pending = memoryview(stdin_text.encode() if isinstance(stdin_text, str) else stdin_text)
    retained = bytearray()
    truncated = False
    with selectors.DefaultSelector() as selector:
        os.set_blocking(process.stdin.fileno(), False)
        if pending:
            selector.register(process.stdin, selectors.EVENT_WRITE)
        else:
            process.stdin.close()
        selector.register(process.stderr, selectors.EVENT_READ)
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise subprocess.TimeoutExpired(command, timeout)
            for key, _ in selector.select(min(remaining, 0.05)):
                if key.fileobj is process.stdin:
                    try:
                        count = os.write(process.stdin.fileno(), pending[:4096])
                        pending = pending[count:]
                    except BrokenPipeError:
                        pending = pending[:0]
                    if not pending:
                        selector.unregister(process.stdin)
                        process.stdin.close()
                else:
                    chunk = os.read(process.stderr.fileno(), 4096)
                    if not chunk:
                        selector.unregister(process.stderr)
                        continue
                    truncated = truncated or len(retained) + len(chunk) > MAX_STDERR_BYTES
                    retained[:] = (retained + chunk)[-MAX_STDERR_BYTES:]
            if process.poll() is not None:
                stop_group()  # Descendants must not hold stderr open after exit.
        process.wait(timeout=max(0, deadline - time.monotonic()))
    return {"category": _stderr_category(retained, truncated), "truncated": truncated}


def run_codex_process(command, *, stdin_text, text, stdout, stderr, timeout, cwd, env):
    """Discard output or return only bounded stderr categories; always kill the group."""
    with subprocess.Popen(command, stdin=subprocess.PIPE, stdout=stdout, stderr=stderr,
                          text=text, cwd=cwd, env=env, start_new_session=True) as process:
        cleanup_started = False

        def stop_group():
            nonlocal cleanup_started
            if not cleanup_started:
                cleanup_started = True
                _stop_group(process)

        try:
            diagnostic = None
            if stderr == subprocess.PIPE:
                diagnostic = _bounded_stderr(process, command, stdin_text, timeout, stop_group)
            else:
                process.communicate(input=stdin_text, timeout=timeout)
            return subprocess.CompletedProcess(command, process.returncode, stderr=diagnostic)
        finally:
            stop_group()


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


def verify_codex_version(
    codex, *, cwd, env, timeout, expected_version=SUPPORTED_CODEX_CLI_VERSION
):
    command = [codex, '--version']
    with subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                          stderr=subprocess.DEVNULL, cwd=cwd, env=env,
                          start_new_session=True) as process:
        try:
            output = _read_version(process, command, timeout)
            if process.returncode != 0 or output.strip() != expected_version.encode():
                raise RuntimeError("Codex version is unsupported")
        finally:
            _stop_group(process)
