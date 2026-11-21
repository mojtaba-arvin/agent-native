FROM golang:1.23.12-bookworm@sha256:167053a2bb901972bf2c1611f8f52c44d5fe7e762e5cab213708d82c421614db AS go-build
WORKDIR /src/experiments/e002/go
COPY experiments/e002/go/ ./
RUN go build -trimpath -ldflags="-buildid=" -o /out/e002-go .

FROM rust:1.100-bookworm@sha256:ade39a710ef85f3506cffcfec3e8a24ba090badef1dff2fb798f71d878833fea AS rust-build
RUN apt-get update && apt-get install -y --no-install-recommends libssl-dev && rm -rf /var/lib/apt/lists/*
WORKDIR /src
COPY experiments/e002/rust/ ./
RUN cargo build --locked --release

FROM postgres:16.4@sha256:e62fbf9d3e2b49816a32c400ed2dba83e3b361e6833e624024309c35d334b412
COPY --from=go-build /out/e002-go /opt/candidates/e002-go
COPY --from=rust-build /src/target/release/agent-native-e002-rust /opt/candidates/e002-rust
COPY experiments/e002/t16/entrypoint.sh /usr/local/bin/t16-candidate
RUN chmod 0755 /usr/local/bin/t16-candidate
WORKDIR /opt/candidates
ENTRYPOINT ["/usr/local/bin/t16-candidate"]
