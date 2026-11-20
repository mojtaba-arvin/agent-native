# T07 - Rust HTTP runtime spike evidence

## Scope and decision boundary

This is a runnable Rust candidate for the shared E-002 HTTP workload. It is a
research spike, not the Agent Native product runtime, and does not select Rust
for production. The comparison remains a correctness/build/runtime feasibility
check; it is not a controlled performance result.

## HTTP behavior and failure contract

The server listens on 127.0.0.1:8080 and implements:

| Request | Expected response |
|---|---|
| GET /health | 200 ok |
| GET /work?ms=20 | 200 completed:20 |
| GET /work?ms=900 | 504 deadline exceeded at the 750 ms operation deadline |
| malformed or noncanonical /work query | 400 invalid ms |
| work admission when all 64 slots are occupied | 503 overloaded |
| GET /stream | 200 with chunk-1, chunk-2, chunk-3 in order |
| unknown route | 404 not found |

The parser accepts only the raw ms= query followed by ASCII decimal digits,
bounded to 0-5,000 ms. It rejects empty, signed, whitespace, encoded, duplicate,
reordered, extra-parameter, overflow, and over-limit values. The 750 ms deadline
and 64 active-work permits are named constants in the Rust library.

## Rust unit evidence

src/lib.rs contains executable tests for:

- accepted decimal query values and rejected malformed query variants;
- successful work completion and the registered deadline failure;
- rejection above the maximum work duration;
- bounded admission, overload classification, and permit release after both
  timeout and successful completion;
- HTTP status mapping for invalid input, overload, and deadline failures;
- ordered streaming response chunks.

These are behavior assertions; the previous placeholder assertion of two
literal constants has been removed.

## Build and runtime verification matrix

Run from experiments/e002/rust with the repository-pinned Rust 1.100.0
toolchain and committed lockfile:

    cargo test --locked
    cargo build --locked --release

Run the shared, black-box HTTP checks from this directory after the release
build:

    python ../conformance.py --command ./target/release/agent-native-e002-rust --cwd .

The same three checks execute in the existing Layer 1 CI step named
E-002 Rust runtime. That step records test/build/conformance exit status in
the workflow run; the conformance runner covers readiness, normal work,
deadline and malformed-query failures, and exact stream-body ordering.

## Evidence limits

This task does not claim performance superiority, a runtime selection, the T02
controlled-host capacity envelope, product-path authentication/authorization,
durable storage behavior, client-disconnect cancellation equivalence, or
production deployment readiness. The separate controlled-host measurement
task must retain repeated measurements and failure evidence before any runtime
decision is made.
