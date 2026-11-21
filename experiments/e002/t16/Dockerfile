# Build arguments are overridable with immutable image references (name@sha256:digest).
ARG GO_IMAGE=golang:1.23.12-bookworm
ARG RUST_IMAGE=rust:1.100-bookworm
ARG POSTGRES_IMAGE=postgres:16.4

FROM ${GO_IMAGE} AS go-build
WORKDIR /src/experiments/e002/go
COPY experiments/e002/go/ ./
RUN go build -trimpath -ldflags="-buildid=" -o /out/e002-go .

FROM golang:1.23.12-bookworm AS loadgen-build
WORKDIR /src/experiments/e002/t16/loadgen
COPY experiments/e002/t16/loadgen/ ./
RUN go build -trimpath -ldflags="-buildid=" -o /out/t16-loadgen .

FROM ${RUST_IMAGE} AS rust-build
WORKDIR /src
COPY experiments/e002/rust/ ./
RUN cargo build --locked --release

FROM ${POSTGRES_IMAGE}
ARG SOURCE_URL=https://github.com/mojtaba-arvin/agent-native
ARG SOURCE_SHA
ARG BUILD_TIME
ARG VERSION=t16

RUN test -n "${SOURCE_SHA}" \
    && test "${#SOURCE_SHA}" -eq 40 \
    && test -n "${BUILD_TIME}"

LABEL org.opencontainers.image.source="${SOURCE_URL}" \
      org.opencontainers.image.revision="${SOURCE_SHA}" \
      org.opencontainers.image.created="${BUILD_TIME}" \
      org.opencontainers.image.title="agent-native T16 benchmark candidates" \
      org.opencontainers.image.description="Controlled-host E-002 T16 product-workload benchmark image" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.licenses="MIT"

COPY --from=go-build /out/e002-go /opt/candidates/e002-go
COPY --from=loadgen-build /out/t16-loadgen /opt/candidates/t16-loadgen
COPY --from=rust-build /src/target/release/agent-native-e002-rust /opt/candidates/e002-rust
COPY experiments/e002/t16/entrypoint.sh /usr/local/bin/t16-candidate
RUN chmod 0755 /usr/local/bin/t16-candidate
WORKDIR /opt/candidates
ENTRYPOINT ["/usr/local/bin/t16-candidate"]
