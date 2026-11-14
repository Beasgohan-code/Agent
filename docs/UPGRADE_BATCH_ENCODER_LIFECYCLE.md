# Upgrade batch: Encoder subprocess lifecycle

## Changes

- Shared FFmpeg conversion runner has a one-hour deadline covering progress
  reads and process exit. Timeout/cancellation/errors kill and reap the child,
  then remove partial destination output.
- A zero exit code without a nonempty output file is no longer success.
- Decode validation has a five-minute deadline. Cancellation and timeout now
  kill and reap its child just as probing and conversion do.
- Validation enables FFmpeg `-xerror` and relies on fatal decode exit status,
  rather than buffering unbounded stderr. Diagnostics remain withheld from
  Telegram. This is an intentional strict validation policy.
- Encode/compress jobs remove their generated output and newly owned temporary
  directory when conversion or validation fails, times out or is cancelled.
  Source files are not deleted. Successful output remains for delivery.

## Coverage and command impact

No command additions, removals or renames. Shared conversion changes affect
encode/compress/sample/toaudio/screens. Validation lifecycle changes affect
encode/compress. Mediainfo retains its existing bounded probe path.

Added regressions for real subprocess conversion timeout, empty successful
exit, validation timeout/cancellation reaping, and encode cleanup on validation
timeout/cancellation/error. Existing real FFmpeg tests verify probing,
conversion and decoding as well as corrupt/empty output rejection.

Full disposable PostgreSQL suite: **974 passed**. Compileall, pyflakes and
`git diff --check` passed. No live Telegram delivery test, deployment or merge.

## Remaining work

This is lifecycle hardening, not full upstream Encoder parity or a hostile-media
sandbox. CPU/RAM/disk quotas, process-tree isolation, bounded probe banner
capture, abandoned successful-output retention and source-download lifecycle
remain separate work. Other plugin UI/source integration and Music native
fetch protections remain incomplete. No upstream code or dependency fork was
copied/installed by this batch. Existing jobs continue through their current
error logging and cancellation paths.
