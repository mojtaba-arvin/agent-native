# Build arguments are overridable with immutable image references (name@sha256:digest).
ARG GO_IMAGE
ARG RUST_IMAGE
ARG POSTGRES_IMAGE
ARG DOCKER_IMAGE

FROM ${GO_IMAGE} AS go-build
WORKDIR /src/experiments/e002/go
COPY experiments/e002/go/ ./
RUN go build -trimpath -ldflags="-buildid=" -o /out/e002-go .

FROM ${GO_IMAGE} AS loadgen-build
WORKDIR /src/experiments/e002/t16/loadgen
COPY experiments/e002/t16/loadgen/ ./
RUN go build -trimpath -ldflags="-buildid=" -o /out/t16-loadgen .

FROM ${RUST_IMAGE} AS rust-build
RUN apt-get update && apt-get install -y --no-install-recommends libssl-dev && rm -rf /var/lib/apt/lists/*
WORKDIR /src
COPY experiments/e002/rust/ ./
RUN cargo build --locked --release

FROM ${DOCKER_IMAGE} AS docker-cli

FROM ${POSTGRES_IMAGE}
ARG SOURCE_URL=https://github.com/mojtaba-arvin/agent-native
ARG SOURCE_SHA
ARG BUILD_TIME
ARG VERSION=t16

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl git python3 util-linux postgresql-client gnupg libssl3 \
    && install -d -m 0755 /etc/apt/keyrings \
    && curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg -o /etc/apt/keyrings/githubcli-archive-keyring.gpg \
    && chmod go+r /etc/apt/keyrings/githubcli-archive-keyring.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" > /etc/apt/sources.list.d/github-cli.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends gh \
    && rm -rf /var/lib/apt/lists/* \
    && test -n "${SOURCE_SHA}" \
    && test "${#SOURCE_SHA}" -eq 40 \
    && test -n "${BUILD_TIME}"

LABEL org.opencontainers.image.source="${SOURCE_URL}" \
      org.opencontainers.image.revision="${SOURCE_SHA}" \
      org.opencontainers.image.created="${BUILD_TIME}" \
      org.opencontainers.image.title="agent-native T16 benchmark candidates" \
      org.opencontainers.image.description="Controlled-host E-002 T16 product-workload benchmark image" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.licenses="MIT"

COPY --from=docker-cli /usr/local/bin/docker /usr/local/bin/docker
COPY experiments/e002/t16/one-command-runner.py /usr/local/bin/t16-one-command-runner.py
# Bake the complete runtime source bundle into the image. The host never clones source.
COPY experiments/e002/ /opt/t16-source/experiments/e002/
RUN printf '%s' "${SOURCE_SHA}" > /opt/t16-source/.t16-source-sha \
    && chmod -R a+rX /opt/t16-source \
    && test -f /opt/t16-source/experiments/e002/t16/tokens.py \
    && ldconfig -p | grep -q 'libcrypto.so.3'
COPY --from=go-build /out/e002-go /opt/candidates/e002-go
COPY --from=loadgen-build /out/t16-loadgen /opt/candidates/t16-loadgen
COPY --from=rust-build /src/target/release/agent-native-e002-rust /opt/candidates/e002-rust
COPY experiments/e002/t16/entrypoint.sh /usr/local/bin/t16-candidate
RUN chmod 0755 /usr/local/bin/t16-candidate
WORKDIR /opt/candidates
ENTRYPOINT ["/usr/local/bin/t16-candidate"]
