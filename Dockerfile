# Use Python 3.10 slim for a balance of size and compatibility
FROM python:3.10-slim

# Set environment variables using modern key=value syntax
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PORT=7860
ENV HOME=/home/user

# Install system dependencies
# libgl1-mesa-glx is often missing in newer Debians, replaced by libgl1
RUN apt-get update && apt-get install -y \
    ffmpeg \
    libsm6 \
    libxext6 \
    libgl1 \
    xvfb \
    wget \
    gnupg \
    && rm -rf /var/lib/apt/lists/*

# Create a non-root user for Hugging Face security standards
RUN useradd -m -u 1000 user
WORKDIR $HOME/app

# Copy requirements and install
COPY --chown=user requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright browsers (Specifically Chromium)
RUN playwright install chromium
RUN playwright install-deps chromium

# Copy the rest of the application
COPY --chown=user . .

# Ensure app directories are writable for video processing
RUN mkdir -p downloads processed captions && \
    chmod -R 777 downloads processed captions

# Expose the port Hugging Face Spaces expects
EXPOSE 7860

# CMD uses xvfb-run to provide a virtual display for the browser if needed
# We add -u to python for unbuffered output as an extra layer of safety
CMD xvfb-run --server-args="-screen 0 1280x720x24" python -u app.py
