# Container image for AWS ECS Express Mode (App Runner stopped accepting new
# customers as of 2026-04-30 - see docs/AWS_MIGRATION_PLAN.md for context).
# Express Mode only deploys a pre-built image from ECR, unlike Render or
# App Runner's source-build model, so this replaces render.yaml's
# buildCommand/startCommand for the AWS path.
#
# Lives at the REPO ROOT (not inside backend/) on purpose: the build context
# needs both backend/ and frontend/ as siblings, because backend/main.py
# mounts ../frontend as static files at runtime - same relative layout the
# app already expects when run directly from this repo.
FROM python:3.12-slim

WORKDIR /app

# Install dependencies first (separate layer) so a frontend-only change
# doesn't force a slow pip reinstall on the next image build.
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

COPY backend/ backend/
COPY frontend/ frontend/

EXPOSE 8080

# --app-dir tells uvicorn where main.py lives; main.py's own
# os.path.dirname(__file__) still resolves correctly from there, so its
# "../frontend" StaticFiles mount finds /app/frontend regardless of the
# process's working directory.
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080", "--app-dir", "backend"]
