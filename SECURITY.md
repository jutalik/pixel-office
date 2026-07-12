# Security Policy

## Reporting a vulnerability

Please report security issues **privately** rather than opening a public issue:

- Use GitHub's [private vulnerability reporting](https://github.com/jutalik/pixel-office/security/advisories/new)
  ("Report a vulnerability" under the Security tab), or
- Open a minimal public issue asking for a private contact channel (no details).

This is a spare-time project, so please allow reasonable time for a response before any
public disclosure.

## Scope & design notes

Pixel Office is **local-first** and runs on your machine:

- The dashboard binds to **loopback (127.0.0.1)** by default. Exposing it to a network
  is your choice and your responsibility.
- Pixel Office **stores no tokens or credentials.** Each AI CLI keeps its own login;
  Pixel Office only reads the telemetry those tools already produce.
- Telemetry fails **open** (never blocks your tools); privileged/control actions fail
  **closed**.
- `po run --live` executes your installed CLIs as subprocesses and **spends tokens**.
  Treat any project you run it against as you would code you're about to execute.

If you find a way telemetry could leak secrets, or a control path that fails open when
it should fail closed, that's exactly the kind of report we want.
