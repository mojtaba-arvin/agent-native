# T16 controlled-host product workload results

Source SHA: eb3457f1205746cdcaf927360b2f57afcc6360f9
Preregistration SHA-256: 8dcc5423e7aeeda07a6c0903aab534f9eeda3836ac74da2a62b7fd97a468886e
Image: ghcr.io/mojtaba-arvin/agent-native-t16@sha256:24044cf5bf823b69d9f09ff814b3c2ac0d35ab9671ac07fd69d8e2dc2e8b0ac2
Image digest: sha256:24044cf5bf823b69d9f09ff814b3c2ac0d35ab9671ac07fd69d8e2dc2e8b0ac2
Host: Intel(R) Core(TM) i7-8550U CPU @ 1.80GHz / x86_64 / kernel 6.8.0-149-generic
PostgreSQL: 16.4 (Debian 16.4-1.pgdg120+2); dedicated-host attestation: dedicated

| Candidate | Run | Completed req/s | p99 ms | CPU seconds | Peak memory bytes | OOM | Integrity violations | SLO |
|---|---|---:|---:|---:|---:|---:|---:|---|
| rust-tokio-hyper | t16-rust-tokio-hyper-rep-01 | — | — | — | — | — | — | FAIL (attempt error) |
| go-net-http | t16-go-net-http-rep-01 | — | — | — | — | — | — | FAIL (attempt error) |
| rust-tokio-hyper | t16-rust-tokio-hyper-rep-02 | — | — | — | — | — | — | FAIL (attempt error) |
| go-net-http | t16-go-net-http-rep-02 | — | — | — | — | — | — | FAIL (attempt error) |
| rust-tokio-hyper | t16-rust-tokio-hyper-rep-03 | — | — | — | — | — | — | FAIL (attempt error) |
| go-net-http | t16-go-net-http-rep-03 | — | — | — | — | — | — | FAIL (attempt error) |
| go-net-http | t16-go-net-http-rep-04 | — | — | — | — | — | — | FAIL (attempt error) |
| rust-tokio-hyper | t16-rust-tokio-hyper-rep-04 | — | — | — | — | — | — | FAIL (attempt error) |
| go-net-http | t16-go-net-http-rep-05 | — | — | — | — | — | — | FAIL (attempt error) |
| rust-tokio-hyper | t16-rust-tokio-hyper-rep-05 | — | — | — | — | — | — | FAIL (attempt error) |
| rust-tokio-hyper | t16-rust-tokio-hyper-rep-06 | — | — | — | — | — | — | FAIL (attempt error) |
| go-net-http | t16-go-net-http-rep-06 | — | — | — | — | — | — | FAIL (attempt error) |
| go-net-http | t16-go-net-http-rep-07 | — | — | — | — | — | — | FAIL (attempt error) |
| rust-tokio-hyper | t16-rust-tokio-hyper-rep-07 | — | — | — | — | — | — | FAIL (attempt error) |
| rust-tokio-hyper | t16-rust-tokio-hyper-rep-08 | — | — | — | — | — | — | FAIL (attempt error) |
| go-net-http | t16-go-net-http-rep-08 | — | — | — | — | — | — | FAIL (attempt error) |
| go-net-http | t16-go-net-http-rep-09 | — | — | — | — | — | — | FAIL (attempt error) |
| rust-tokio-hyper | t16-rust-tokio-hyper-rep-09 | — | — | — | — | — | — | FAIL (attempt error) |
| go-net-http | t16-go-net-http-rep-10 | — | — | — | — | — | — | FAIL (attempt error) |
| rust-tokio-hyper | t16-rust-tokio-hyper-rep-10 | — | — | — | — | — | — | FAIL (attempt error) |

## Cohort summary

- rust-tokio-hyper: 0/10 measured runs across 10 attempts; mean throughput n/a req/s; mean p99 n/a ms; mean CPU n/a s; 0/10 SLO passes.
- go-net-http: 0/10 measured runs across 10 attempts; mean throughput n/a req/s; mean p99 n/a ms; mean CPU n/a s; 0/10 SLO passes.

## Evidence boundary

Every row is a separate container run with a one-vCPU/one-GiB cgroup-v2 candidate allocation. The load generator and PostgreSQL dependency use separate CPU allocations and cgroups. The 60/20/10/10 product workload includes authorized reads, plan validation, durable job admission, and expected capability denials. Expected 403 denials count as completed responses. Completed throughput is divided by the fixed 50-second offer window; post-window completion drain is reported separately.

Physical-host exclusivity is an explicit operator attestation. Shared GitHub-hosted runner data is not used.
