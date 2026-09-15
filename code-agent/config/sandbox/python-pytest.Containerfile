# Trusted verification image for the rootless sandbox backend (M06 prebuilt sandbox image).
# Built once by an administrator; verification runs never pull or install (--pull=never,
# --network=none). Reference the built image by its immutable image id or digest.
#
#   podman build -t localhost/kh-python-pytest:v1 -f python-pytest.Containerfile .
FROM docker.io/library/python:3.12-slim@sha256:78387bc3881b8273120a12ebe6c1ab22b018ccc2c9adf565ae1ac9b536e184ea
RUN python -m pip install --no-cache-dir pytest==9.1.1
USER 65532:65532
