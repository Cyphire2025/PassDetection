# ============================================================
# Backend Dockerfile — Multi-stage build
# ============================================================
# Stage 1: builder  — installs dependencies
# Stage 2: runtime  — minimal image with no build tools
# ============================================================

# ── Stage 1: Dependency Builder ───────────────────────────────────────────────
# Reviewed OpenCV source archive, image-processing modules only.
FROM python:3.14.0-slim@sha256:0aecac02dc3d4c5dbb024b753af084cafe41f5416e02193f1ce345d671ec966e AS opencv-build
RUN apt-get update && apt-get install -y --no-install-recommends build-essential && rm -rf /var/lib/apt/lists/*
WORKDIR /build
COPY requirements-image-build.lock .
RUN python -m pip install --no-cache-dir --require-hashes -r requirements-image-build.lock
ENV ENABLE_HEADLESS=1
ENV CMAKE_BUILD_PARALLEL_LEVEL=2
ENV CMAKE_ARGS="-DBUILD_LIST=core,imgproc,photo,features2d,flann,python3 -DWITH_FFMPEG=OFF -DWITH_GSTREAMER=OFF -DWITH_V4L=OFF -DWITH_IPP=OFF -DWITH_ITT=OFF -DWITH_OPENCL=OFF -DBUILD_TESTS=OFF -DBUILD_PERF_TESTS=OFF -DBUILD_EXAMPLES=OFF -DBUILD_opencv_videoio=OFF -DBUILD_opencv_gapi=OFF -DBUILD_JAVA=OFF"
RUN python -m pip wheel --no-cache-dir --no-deps --no-build-isolation --wheel-dir=/wheels \
    'https://files.pythonhosted.org/packages/36/2f/5b2b3ba52c864848885ba988f24b7f105052f68da9ab0e693cc7c25b0b30/opencv-python-headless-4.11.0.86.tar.gz#sha256=996eb282ca4b43ec6a3972414de0e2331f5d9cda2b41091a49739c19fb843798'

# OCR receives normalized PIL images, never URLs or archives. Omit those
# optional parsers and training/debug executables from the production binary.
FROM opencv-build AS tesseract-build
RUN apt-get update && apt-get install -y --no-install-recommends \
    pkg-config libleptonica-dev tesseract-ocr-eng tesseract-ocr-osd && rm -rf /var/lib/apt/lists/*
ADD --checksum=sha256:21dbaff9867d937c156d0b898e90b726aa339129cfebd7e1365cd5fee5046d67 \
    https://codeload.github.com/tesseract-ocr/tesseract/tar.gz/db0ec62f81b0737fbbe184d8fea40af5738f8eef /build/tesseract.tar.gz
RUN mkdir /build/tesseract && tar -xzf /build/tesseract.tar.gz --strip-components=1 -C /build/tesseract && \
    cmake -S /build/tesseract -B /build/tesseract-output -G Ninja \
      -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX=/opt/tesseract \
      -DCMAKE_INSTALL_RPATH=/opt/tesseract/lib -DBUILD_SHARED_LIBS=ON \
      -DBUILD_TRAINING_TOOLS=OFF -DBUILD_TESTS=OFF -DGRAPHICS_DISABLED=ON \
      -DDISABLE_ARCHIVE=ON -DDISABLE_CURL=ON && \
    cmake --build /build/tesseract-output --parallel 2 && cmake --install /build/tesseract-output

FROM opencv-build AS xml-security-build
COPY docker/build_xml_security.py /build/build_xml_security.py
RUN python /build/build_xml_security.py

FROM python:3.14.0-slim@sha256:0aecac02dc3d4c5dbb024b753af084cafe41f5416e02193f1ce345d671ec966e AS builder

ARG PIP_VERSION=26.2.1

WORKDIR /build

# System dependencies required for C extensions (OpenCV, psycopg2, etc.)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    libgl1 \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies into a virtual environment
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.lock .
COPY --from=opencv-build /wheels /custom-opencv
RUN python -m pip install --no-cache-dir "pip==${PIP_VERSION}" && \
    pip install --no-cache-dir --require-hashes -r requirements.lock && \
    python -m pip uninstall -y opencv-python-headless && \
    python -m pip install --no-cache-dir --no-deps /custom-opencv/*.whl && \
    python -m pip uninstall -y setuptools wheel

# ── Stage 2: Production Runtime ──────────────────────────────────────────────
FROM python:3.14.0-slim@sha256:0aecac02dc3d4c5dbb024b753af084cafe41f5416e02193f1ce345d671ec966e AS runtime

ARG APP_REVISION=unknown

LABEL maintainer="Global Connects Dashboard Team"
LABEL version="1.0.0"
LABEL description="Global Connects Dashboard - Backend API"
LABEL org.opencontainers.image.revision="${APP_REVISION}"

ENV APP_REVISION="${APP_REVISION}"

# Headless OpenCV does not link the GUI/X11 stack. Keep only libraries needed
# by PostgreSQL and the OCR CLI; full-image qualification verifies imports/OCR.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    libgomp1 \
    libleptonica6 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=tesseract-build /opt/tesseract /opt/tesseract
COPY --from=tesseract-build /usr/share/tesseract-ocr/5/tessdata /opt/tesseract/share/tessdata
ENV TESSDATA_PREFIX=/opt/tesseract/share/tessdata

# The base CPython embeds its own old Expat. Updating the Debian package alone
# leaves XML parsing vulnerable; replace only the same-version pyexpat module.
COPY --from=xml-security-build /build/xml-security/packages/libexpat1.deb /tmp/libexpat1.deb
RUN dpkg -i /tmp/libexpat1.deb && rm /tmp/libexpat1.deb
COPY --from=xml-security-build /build/xml-security/patched-python/ /usr/local/lib/python3.11/lib-dynload/

# Apply the upstream hard-link relocation fix to the exact pinned stdlib source.
COPY docker/backport_tarfile_security.py /tmp/backport_tarfile_security.py
RUN python /tmp/backport_tarfile_security.py && rm /tmp/backport_tarfile_security.py && \
    rm -f /usr/local/lib/python3.11/__pycache__/tarfile.*.pyc

# No application or maintenance command needs terminal comparison or Linux
# mount/namespace administration. Remove the affected executable components.
RUN rm /usr/bin/infocmp /usr/bin/mount /usr/bin/umount /usr/bin/nsenter

# Build installers are not runtime dependencies. Remove both global and venv
# copies so unused vendored wheel/jaraco code cannot survive in the final image.
RUN /usr/local/bin/python -m pip uninstall -y setuptools wheel

# Create a non-root user for security
RUN groupadd --gid 1001 appgroup && \
    useradd --uid 1001 --gid appgroup --shell /bin/bash --create-home appuser

WORKDIR /app

# Copy virtual environment from builder
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:/opt/tesseract/bin:$PATH"

# Copy only runtime sources. Local debug images, environments and logs must
# never enter any release-image layer, even when building a dirty checkout.
COPY --chown=appuser:appgroup app ./app
COPY --chown=appuser:appgroup alembic ./alembic
COPY --chown=appuser:appgroup scripts ./scripts
COPY --chown=appuser:appgroup alembic.ini gunicorn.conf.py ./
RUN python -c "import pillow_heif; v=pillow_heif.libheif_info()['libheif']; assert tuple(map(int,v.split('.'))) >= (1,23,2), v"

# Switch to non-root user
USER appuser

EXPOSE 8000

# Health check used by Docker Compose and Kubernetes
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD python -c "import httpx; httpx.get('http://localhost:8000/api/v1/health/live').raise_for_status()"

# The config validates WEB_CONCURRENCY and the aggregate PostgreSQL connection
# budget before Gunicorn forks any API worker.
CMD ["gunicorn", "--config", "gunicorn.conf.py", "app.main:app"]
