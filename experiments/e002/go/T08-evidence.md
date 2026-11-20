# T08 — Go HTTP runtime spike evidence

## Scope and decision boundary

This is a runnable Go candidate for the shared E-002 HTTP workload. It is a
research spike, not the Agent Native product runtime, and does not select Go
for production. The current checks establish contract behavior, bounded work
admission, buildability, and runtime conformance; they are not a performance
comparison or controlled-host capacity result.

The server binds to 127.0.0.1:8080 and uses only the Go standard library. The
module declares Go 1.23; the existing Layer 1 workflow installs Go 1.23.12.

## HTTP behavior and failure contract

| Request | Expected response |
|---|---|
| GET /health | 200 ok |
| GET /work?ms=20 | 200 completed:20 |
| GET /work?ms=900 | 504 deadline exceeded at the 750 ms operation deadline |
| malformed or noncanonical /work query | 400 invalid ms |
| work admission when all 64 active-work slots are occupied | 503 overloaded |
| GET /stream | 200 with chunk-1, chunk-2, chunk-3 in order |
| unknown route | 404 not found |

The parser reads the raw query and accepts only `ms=` followed by ASCII
decimal digits in the range 0–5,000. It rejects missing and empty values,
additional, reordered or duplicate parameters, percent-encoded keys, signs,
whitespace, overflow, and over-limit values. Query validation happens before
work admission, so malformed input does not consume a work slot.

The handler uses a nonblocking 64-slot channel for active work. A slot is
released on success, deadline expiry, or request cancellation. Work has a
fixed 750 ms deadline. Client cancellation stops the handler without trying
to write a response to a disconnected client; full cancellation equivalence
is outside this spike's acceptance scope.

## Go unit evidence

`main_test.go` contains behavior tests for:

- accepted and rejected raw query values, including encoded, duplicate,
  reordered, signed, empty, overflow, and over-limit cases;
- successful work completion and the registered 750 ms deadline;
- overload response when the sole test slot is occupied;
- admission-slot release after both successful work and timeout;
- 400 and 503 failure response mapping, with 504 exercised by the deadline test;
- the registered 64-slot application capacity;
- health, unknown-route, and exact ordered streaming response behavior.

The handler accepts injected limits/deadlines for deterministic tests while
the executable uses the registered 64-slot and 750 ms constants.

## Verification matrix

Run from `experiments/e002/go`:

```sh
go test ./...
go build -o "$RUNNER_TEMP/e002-go" .
python ../conformance.py --command "$RUNNER_TEMP/e002-go" --cwd .
```

The existing Layer 1 CI step named `E-002 Go runtime` runs these same three
commands with the pinned Go 1.23.12 toolchain. The shared runner verifies
readiness, successful work, the 900 ms deadline failure, malformed query
variants, and the exact ordered streaming response.

Additional local static and unit checks:

```sh
go vet ./...
go test -count=1 ./...
go build .
```

## Evidence limits

This task does not claim performance superiority, a runtime selection, the
T02 controlled-host capacity envelope, durable storage behavior, product-path
authentication or authorization, client-disconnect cancellation equivalence,
or production deployment readiness. The separate controlled-host measurement
task must retain repeated measurements and failure evidence before any runtime
decision is made.
