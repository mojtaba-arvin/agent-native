# Production container and SBOM

The supported image packages the installable `agent-native` Python distribution and CLI. Research experiments, tests, documentation, credentials, and project-control records are excluded from the build context.

## Pinned inputs

- Base: official `python:3.11.18-slim-bookworm` multi-platform OCI index, pinned by digest in `base-image.lock`.
- Build platform: `linux/amd64`.
- Build engine: Buildx v0.39.1 with BuildKit image `moby/buildkit:v0.35.1`.
- SBOM generator: Syft v1.57.2.
- Buildx and Syft Linux/amd64 release binaries are pinned by SHA-256 in `build-toolchain.lock`.
- Build-only Python dependencies: setuptools 84.2.1 and wheel 0.48.0, pinned with PyPI wheel SHA-256 hashes.
- Runtime Python dependency: psycopg 3.2.12 with its binary extra, pinned in the project metadata and installed from the builder's wheelhouse. The base image digest fixes Python, pip, and the OS userspace.
- The image supports the production `agent-native serve` entrypoint; PostgreSQL DSNs and capability-token signing keys are supplied only through runtime environment variables.

Update a pinned input only with a reviewed digest/hash change and a new reproducibility run. The base image and build tools are intentionally not floating tags.

## Build and verify locally

Requirements: Docker Engine, Git, Python 3.11+, curl, and sha256sum. Install the Buildx and Syft binaries whose versions and hashes are recorded in `build-toolchain.lock`, then create the pinned BuildKit builder:

```sh
source container/build-toolchain.lock
docker buildx create --name agent-native-repro --driver docker-container --driver-opt "image=$BUILDKIT_IMAGE" --use
bash container/build-reproducible.sh ./dist/container "$(git rev-parse HEAD)"
(cd dist/container && sha256sum -c SHA256SUMS)
python container/verify_sbom.py dist/container/sbom.spdx.json
docker buildx rm agent-native-repro
```

The script builds the same source twice with cache disabled, resolves the exact project runtime dependency into the builder wheelhouse, uses the source commit timestamp as `SOURCE_DATE_EPOCH` and BuildKit's `rewrite-timestamp=true` exporter option, and compares image configuration IDs. It smoke-tests the CLI as UID/GID 65532 with no network, a read-only root filesystem and no Linux capabilities. It generates an SPDX-2.3 SBOM, saves the image archive, and writes checksums plus build evidence.

Load the archive with `docker load --input dist/container/agent-native-image.tar`. The default image command is `agent-native --help`; pass a supported CLI subcommand to use the image.

## Acceptance verification

The T15 acceptance script installs the exact Buildx and Syft binaries using the SHA-256 values in `build-toolchain.lock`, creates a builder using the pinned BuildKit image, runs the two-build comparison, validates the SBOM, and writes the image ID, SBOM package count, and archive/SBOM hashes to the GitHub Actions job summary. The generated archive and SBOM are stored under the runner's temporary output directory for that job; local runs can preserve them under `dist/container`.

Generating an SBOM is an inventory operation, not a vulnerability assessment; no vulnerability-free claim is made.

## Reproducibility scope

This verifies independent uncached builds for the same source commit, pinned base image, pinned Buildx/BuildKit/Syft toolchain, and `linux/amd64` platform. It does not claim cross-architecture or cross-BuildKit-version reproducibility. The SBOM contains generation metadata and is separately checksummed, not part of the image reproducibility comparison.
