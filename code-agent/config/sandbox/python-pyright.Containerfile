# Trusted Python language server image for sandboxed LSP evidence (M06, M02-LNG-011).
# Built once by an administrator; sessions never pull or install (--pull=never,
# --network=none). The server sees only the read-only source view and bundled stdlib stubs.
#
#   podman build -t localhost/kh-python-pyright:v1 -f python-pyright.Containerfile .
FROM docker.io/library/node:22-slim@sha256:83f487e0a63425e5b4d146fb5e5be574bcbe1b7b843d3ebafdd95eaf7767a7e5
RUN npm install --global --ignore-scripts --no-audit --no-fund pyright@1.1.414 \
    && npm cache clean --force
USER 65532:65532
