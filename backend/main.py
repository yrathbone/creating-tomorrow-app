"""
Creating Tomorrow backend - FastAPI app serving both the API and the static frontend.

Endpoints:
  POST /api/analyze  - old resume file + job posting text -> resume_data,
                        match_report, reflective_questions (comparison tool)
  POST /api/build     - old resume file only -> resume_data,
                        role_research_summary, reflective_questions
                        (resume-builder tool, uses live web search)
  POST /api/scratch-entry    - one experience entry's raw facts -> drafted
                        bullets + reflective questions (start-from-scratch
                        tool, per entry)
  POST /api/scratch-finalize - full assembled experience/education/skills
                        -> suggested summary + suggested skills
  POST /api/upgrade  - old resume file only -> resume_data rewritten in
                        polished executive-resume-writer language (Summit
                        tool; content enhancement only, no new facts, no
                        web search, no reflective questions)
  POST /api/generate - final resume_data + ats_mode -> .docx file

Run locally:
  uvicorn main:app --reload --port 8000
"""
import os

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from extractor import extract_text
from coach import analyze, CoachError
from builder import build, BuilderError
from scratch import draft_entry, finalize, ScratchError
from upgrade import upgrade, UpgradeError
from resume_builder import build_resume_bytes

app = FastAPI(title="Creating Tomorrow API")

# Only needed if the frontend is ever served from a different origin than
# the API (e.g. local dev with a separate dev server). Same-origin
# deployment (frontend served by this same app) doesn't need this, but it's
# harmless to leave permissive for now since there's no auth/cookies here.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

MAX_UPLOAD_BYTES = 5 * 1024 * 1024  # 5 MB - old resumes are small text documents


# StaticFiles sends no Cache-Control header by default, so browsers fall back
# to heuristic caching and can keep serving old HTML/JS for a while after a
# deploy. Force revalidation on every request for the frontend (StaticFiles
# still returns 304s via ETag/Last-Modified, so this doesn't mean a full
# re-download every time - just no silently-stale pages after we ship a fix).
@app.middleware("http")
async def no_cache_for_frontend(request, call_next):
    response = await call_next(request)
    if not request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-cache"
    return response


@app.post("/api/analyze")
async def api_analyze(
    resume_file: UploadFile = File(...),
    job_posting: str = Form(...),
):
    content = await resume_file.read()
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File too large (5 MB max).")

    try:
        resume_text = extract_text(resume_file.filename, content)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if not resume_text.strip():
        raise HTTPException(status_code=400, detail="Could not extract any text from that file.")

    if not job_posting.strip():
        raise HTTPException(status_code=400, detail="Job posting text is required.")

    try:
        result = analyze(resume_text, job_posting)
    except CoachError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Unexpected error: {type(e).__name__}: {e}")

    return result


@app.post("/api/build")
async def api_build(resume_file: UploadFile = File(...)):
    content = await resume_file.read()
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File too large (5 MB max).")

    try:
        resume_text = extract_text(resume_file.filename, content)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if not resume_text.strip():
        raise HTTPException(status_code=400, detail="Could not extract any text from that file.")

    try:
        result = build(resume_text)
    except BuilderError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Unexpected error: {type(e).__name__}: {e}")

    return result


@app.post("/api/upgrade")
async def api_upgrade(resume_file: UploadFile = File(...)):
    content = await resume_file.read()
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File too large (5 MB max).")

    try:
        resume_text = extract_text(resume_file.filename, content)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if not resume_text.strip():
        raise HTTPException(status_code=400, detail="Could not extract any text from that file.")

    try:
        result = upgrade(resume_text)
    except UpgradeError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Unexpected error: {type(e).__name__}: {e}")

    return {"resume_data": result}


class ScratchEntryRequest(BaseModel):
    entry_type: str  # "work" | "volunteer" | "school"
    title: str
    organization: str
    dates: str
    description: str


@app.post("/api/scratch-entry")
async def api_scratch_entry(req: ScratchEntryRequest):
    if not req.title.strip() or not req.description.strip():
        raise HTTPException(status_code=400, detail="A role/title and a description of what you did are both required.")

    try:
        result = draft_entry(req.entry_type, req.title, req.organization, req.dates, req.description)
    except ScratchError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Unexpected error: {type(e).__name__}: {e}")

    return result


class ScratchFinalizeRequest(BaseModel):
    name: str
    experience: list
    education: list
    existing_skills: list = []


@app.post("/api/scratch-finalize")
async def api_scratch_finalize(req: ScratchFinalizeRequest):
    try:
        result = finalize(req.name, req.experience, req.education, req.existing_skills)
    except ScratchError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Unexpected error: {type(e).__name__}: {e}")

    return result


class GenerateRequest(BaseModel):
    resume_data: dict
    ats_mode: bool = False


@app.post("/api/generate")
async def api_generate(req: GenerateRequest):
    required_fields = ["name", "contact", "skills", "experience", "education"]
    missing = [f for f in required_fields if f not in req.resume_data]
    if missing:
        raise HTTPException(status_code=400, detail=f"resume_data missing fields: {missing}")

    try:
        docx_bytes = build_resume_bytes(req.resume_data, ats_mode=req.ats_mode)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to build resume: {e}")

    filename = req.resume_data.get("name", "Resume").replace(" ", "_") + "_Resume.docx"
    return Response(
        content=docx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/api/health")
async def health():
    return {"status": "ok", "api_key_configured": bool(os.environ.get("ANTHROPIC_API_KEY"))}


# Serve the static frontend last, so /api/* routes above take priority.
frontend_dir = os.path.join(os.path.dirname(__file__), "..", "frontend")
app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")
