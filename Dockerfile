# Use Python 3.10 slim for a balance of size and compatibility
FROM python:3.10-slim

# Set environment variables using modern key=value syntax
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PORT=7860
ENV HOME=/home/user
ENV PATH=$HOME/.local/bin:$PATH

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

# Create a non-root user and set up the app directory
RUN useradd -m -u 1000 user
WORKDIR $HOME/app
RUN chown -R user:user $HOME/app

# Copy requirements and install
COPY --chown=user requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright Dependencies (Must be done as root)
RUN playwright install-deps chromium

# Switch to the non-root user for the rest of the operations
USER user

# Install Playwright Browsers (As user, so they are in $HOME/.cache/ms-playwright)
RUN playwright install chromium

# Copy the rest of the application
COPY --chown=user . .

# Ensure app directories exist (Permissions are handled by COPY --chown, but explicit creation is safe)
RUN mkdir -p downloads processed captions

# Run initial build/setup (pre-downloads models, initializes DB as user)
RUN python build.py

# Expose the port Hugging Face Spaces expects
EXPOSE 7860

# CMD uses xvfb-run to provide a virtual display for the browser if needed
# We use python -u for unbuffered output
CMD xvfb-run --server-args="-screen 0 1280x720x24" python -u app.py
