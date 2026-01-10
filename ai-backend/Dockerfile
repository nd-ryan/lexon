# --- Build Stage ---
# Use an official Python runtime as a parent image
FROM python:3.11-slim AS builder

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Set the working directory in the container
WORKDIR /app

# Install system dependencies that might be required by Python packages
RUN apt-get update && apt-get install -y --no-install-recommends gcc && rm -rf /var/lib/apt/lists/*

# Install poetry
RUN pip install poetry

# Configure Poetry to create the virtual env in the project's root
RUN poetry config virtualenvs.in-project true

# Copy only the files needed for dependency installation from the ai-backend directory
COPY poetry.lock pyproject.toml ./

# Install project dependencies
# --no-root: Don't install the project itself, only dependencies
# --no-dev: Don't install development dependencies
# RUN poetry install --no-root
RUN poetry install --no-root --only main

# --- Final Stage ---
FROM python:3.11-slim AS final

# Set the working directory in the container
WORKDIR /app

# Install runtime dependencies (poppler for pdf2image)
RUN apt-get update && apt-get install -y --no-install-recommends \
    poppler-utils \
    && rm -rf /var/lib/apt/lists/*

# Copy the virtual environment from the builder stage
COPY --from=builder /app/.venv /app/.venv

# Add the virtual environment to the PATH
ENV PATH="/app/.venv/bin:$PATH"

# Copy the application code from the ai-backend directory
COPY . ./

# Expose the port the app runs on
EXPOSE 8000

# Define the command to run the application
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"] 