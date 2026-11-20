FROM golang:1.23.12-bookworm AS go-build
WORKDIR /src/experiments/e002/go
COPY experiments/e002/go/ ./
RUN go build -trimpath -ldflags="-buildid=" -o /out/e002-go .

FROM rust:1.100-bookworm AS rust-build
WORKDIR /src
COPY experiments/e002/rust/ ./
RUN cargo build --locked --release

FROM postgres:16.4
COPY --from=go-build /out/e002-go /opt/candidates/e002-go
COPY --from=rust-build /src/target/release/agent-native-e002-rust /opt/candidates/e002-rust
COPY experiments/e002/t16/entrypoint.sh /usr/local/bin/t16-candidate
RUN chmod 0755 /usr/local/bin/t16-candidate
WORKDIR /opt/candidates
ENTRYPOINT ["/usr/local/bin/t16-candidate"]
