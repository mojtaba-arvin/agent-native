FROM ubuntu:26.04

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates libgcc-s1 libncurses6 libssl3t64 libstdc++6 libtinfo6 zlib1g \
    && rm -rf /var/lib/apt/lists/*

COPY entrypoint.sh /usr/local/bin/e002-candidate
RUN chmod 0755 /usr/local/bin/e002-candidate
WORKDIR /opt/candidates
ENTRYPOINT ["/usr/local/bin/e002-candidate"]
