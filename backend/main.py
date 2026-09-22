"""
Creating Tomorrow backend - FastAPI app serving both the API and the static frontend.

Four tools, front-end names in parentheses:
  POST /api/analyze  - old resume file + job posting text -> resume_data,
                        match_report (Low/Average/High), reflective_questions
                        (Right Fit)
  POST /api/recap    - a match_report + candidate name -> one-page .docx
                        recap of that comparison (Right Fit, download)
  POST /api/scratch-entry    - one experience entry's raw facts -> drafted
                        bullets + reflective questions (Beginning, per entry)
  POST /api/scratch-finalize - full assembled experience/education/skills
                        -> suggested summary + suggested skills (Beginning)
  POST /api/refine   - old resume file only -> resume_data restructured into
                        ATS-friendly format and rewritten in polished
                        executive-resume-writer language, with a positioning
                        headline and a fixed what-changed/please-verify
                        summary (Refine; content enhancement only, no new
                        facts, no web search, no reflective questions)
  POST /api/elevate-start    - old resume file only -> restructured
                        resume_data, a short analysis, discovery categories,
                        and the first batch of discovery questions (Elevate)
  POST /api/elevate-discover - resume_data + categories + full Q&A history
                        so far -> either another batch of questions, or (once
                        enough is gathered) discovered_facts for the
                        candidate to confirm/edit/remove (Elevate, repeated)
  POST /api/elevate-finalize - resume_data + confirmed_facts -> final
                        elevated resume_data (headline, rewritten summary,
                        core expertise, confirmed facts folded into
                        experience) plus what-we-uncovered/changed/verify
                        summaries (Elevate)
  POST /api/generate - final resume_data + ats_mode -> .docx file
  POST /api/profile-review - LinkedIn screenshots (any number) + pasted
                        profile text + a profile PDF, any combination, plus
                        an optional resume file -> a 5-section educational
                        review (first impression, headline, about,
                        experience, skills), a signature evidence-backed
                        strengths list, and (when there's enough material)
                        a consolidated sample of an updated profile drawing
                        on the resume where it fills in an existing LinkedIn
                        role's detail. No score. (5th tool, "Spotlight")
  POST /api/spotlight-recap - a completed Spotlight review -> one-page .docx
                        download (signature strengths, suggested headline/
                        About rewrites, a consolidated list of ways to
                        strengthen the profile, and the sample updated
                        profile if one was generated). (Spotlight, download)
  POST /api/prepare  - job description text + old resume file (optional) ->
                        employer_priorities, grouped interview questions
                        (each with a plain-language "why" and the posting/
                        resume language that prompted it), candidate
                        questions to ask the interviewer, and a prep tip.
                        (6th tool, working name "Prepare")

Run locally:
  uvicorn main:app --reload --port 8000

Concurrency note: every route below that calls a tool module's AI logic
wraps that call in run_in_threadpool(). The Anthropic SDK's client used
throughout backend/*.py is the SYNCHRONOUS client, called directly inside
these `async def` route handlers - without offloading it to a worker
thread, a single in-flight AI call (which can take 10-90+ seconds) blocks
this process's entire single-threaded event loop, serializing every other
concurrent request behind it, regardless of which tool or which visitor
they belong to. Confirmed empirically: 3 concurrent /api/prepare requests
with distinct inputs completed correctly (no cross-request data leakage -
each response matched its own input) but took ~90s each, all finishing at
the same moment - clear evidence of serialization, not 3x independent
~20-30s calls running in parallel. run_in_threadpool() runs the blocking
call in Starlette's worker thread pool instead, freeing the event loop to
handle other requests while it's in flight.
"""
import base64
import os

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from extractor import extract_text
from coach import analyze, CoachError
from scratch import draft_entry, finalize, ScratchError
from upgrade import upgrade, UpgradeError
from elevate import analyze_for_discovery, discover, finalize_elevate, ElevateError
from profile_review import review_profile, ProfileReviewError
from prepare import prepare, PrepareError
from resume_builder import build_resume_bytes, build_match_recap_bytes, build_profile_review_recap_bytes

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

# Shared by /api/analyze and /api/prepare - both take free-text job posting
# content and should be bounded the same way for cost control.
MIN_JOB_DESCRIPTION_CHARS = 40
MAX_JOB_DESCRIPTION_CHARS = 15000


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
    job_posting: str = Form(""),
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

    job_posting = job_posting.strip()
    if not job_posting:
        raise HTTPException(status_code=400, detail="Job posting text is required.")
    if len(job_posting) > MAX_JOB_DESCRIPTION_CHARS:
        raise HTTPException(
            status_code=400,
            detail=f"That job posting is too long ({len(job_posting)} characters, {MAX_JOB_DESCRIPTION_CHARS} max) — please paste just the posting text.",
        )

    try:
        result = await run_in_threadpool(analyze, resume_text, job_posting)
    except CoachError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Unexpected error: {type(e).__name__}: {e}")

    return result


class RecapRequest(BaseModel):
    match_report: dict
    candidate_name: str = "Candidate"


@app.post("/api/recap")
async def api_recap(req: RecapRequest):
    required_fields = ["match_level", "match_rationale"]
    missing = [f for f in required_fields if f not in req.match_report]
    if missing:
        raise HTTPException(status_code=400, detail=f"match_report missing fields: {missing}")

    try:
        docx_bytes = build_match_recap_bytes(req.match_report, req.candidate_name)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to build recap: {e}")

    filename = req.candidate_name.replace(" ", "_") + "_Right_Fit_Recap.docx"
    return Response(
        content=docx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.post("/api/refine")
async def api_refine(resume_file: UploadFile = File(...)):
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
        result = await run_in_threadpool(upgrade, resume_text)
    except UpgradeError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Unexpected error: {type(e).__name__}: {e}")

    return result


@app.post("/api/elevate-start")
async def api_elevate_start(resume_file: UploadFile = File(...)):
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
        result = await run_in_threadpool(analyze_for_discovery, resume_text)
    except ElevateError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Unexpected error: {type(e).__name__}: {e}")

    return result


class ElevateDiscoverRequest(BaseModel):
    resume_data: dict
    categories: list = []
    history: list = []
    force_finish: bool = False
    round_number: int = 1


@app.post("/api/elevate-discover")
async def api_elevate_discover(req: ElevateDiscoverRequest):
    try:
        result = await run_in_threadpool(
            discover, req.resume_data, req.categories, req.history, req.force_finish, req.round_number
        )
    except ElevateError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Unexpected error: {type(e).__name__}: {e}")

    return result


class ElevateFinalizeRequest(BaseModel):
    resume_data: dict
    confirmed_facts: list = []


@app.post("/api/elevate-finalize")
async def api_elevate_finalize(req: ElevateFinalizeRequest):
    try:
        result = await run_in_threadpool(finalize_elevate, req.resume_data, req.confirmed_facts)
    except ElevateError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Unexpected error: {type(e).__name__}: {e}")

    return result


MAX_IMAGE_BYTES = 8 * 1024 * 1024  # 8 MB per screenshot
MAX_TOTAL_IMAGE_BYTES = 24 * 1024 * 1024  # 24 MB combined across all screenshots
ALLOWED_IMAGE_TYPES = {"image/png", "image/jpeg", "image/webp"}


@app.post("/api/profile-review")
async def api_profile_review(
    screenshots: list[UploadFile] = File(default=[]),
    profile_pdf: UploadFile = File(default=None),
    resume_file: UploadFile = File(default=None),
    headline: str = Form(default=""),
    about: str = Form(default=""),
    experience: str = Form(default=""),
    skills: str = Form(default=""),
    additional: str = Form(default=""),
    everything: str = Form(default=""),
):
    # Every field above is optional - a person may supply any combination of
    # screenshots, structured text fields, a single "paste everything" blob,
    # and/or a PDF. Nothing is written to disk anywhere below: files are read
    # into memory, used for this one request, and discarded when it returns.
    images = []
    total_image_bytes = 0
    for screenshot in screenshots:
        if screenshot.content_type not in ALLOWED_IMAGE_TYPES:
            raise HTTPException(
                status_code=400,
                detail=f"That file type isn't supported yet. Please upload PNG, JPG, or WEBP screenshots.",
            )
        image_bytes = await screenshot.read()
        if len(image_bytes) > MAX_IMAGE_BYTES:
            raise HTTPException(status_code=413, detail="One of those screenshots is too large (8 MB max each).")
        total_image_bytes += len(image_bytes)
        if total_image_bytes > MAX_TOTAL_IMAGE_BYTES:
            raise HTTPException(status_code=413, detail="Those screenshots are too large combined (24 MB max total).")
        images.append({
            "media_type": screenshot.content_type,
            "data": base64.b64encode(image_bytes).decode("ascii"),
        })

    pdf_text = ""
    if profile_pdf is not None:
        pdf_bytes = await profile_pdf.read()
        if len(pdf_bytes) > MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="That PDF is too large (5 MB max).")
        try:
            pdf_text = extract_text(profile_pdf.filename, pdf_bytes)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    pasted_parts = []
    if everything.strip():
        pasted_parts.append(everything.strip())
    else:
        for label, value in [
            ("Headline", headline),
            ("About", about),
            ("Experience", experience),
            ("Skills", skills),
            ("Additional Information", additional),
        ]:
            if value.strip():
                pasted_parts.append(f"{label}:\n{value.strip()}")
    pasted_text = "\n\n".join(pasted_parts)

    if not images and not pasted_text.strip() and not pdf_text.strip():
        raise HTTPException(
            status_code=400,
            detail="I need at least one screenshot, some pasted profile text, or a profile PDF before I can give you a useful review.",
        )

    # Optional and supplementary only - a resume alone (with none of the
    # LinkedIn inputs above) is not enough to proceed; the check above still
    # applies regardless of whether a resume was also provided.
    resume_text = ""
    if resume_file is not None:
        resume_bytes = await resume_file.read()
        if len(resume_bytes) > MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="That resume file is too large (5 MB max).")
        try:
            resume_text = extract_text(resume_file.filename, resume_bytes)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    try:
        result = await run_in_threadpool(review_profile, images, pasted_text, pdf_text, resume_text)
    except ProfileReviewError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Unexpected error: {type(e).__name__}: {e}")

    return result


class SpotlightRecapRequest(BaseModel):
    review: dict


@app.post("/api/spotlight-recap")
async def api_spotlight_recap(req: SpotlightRecapRequest):
    try:
        docx_bytes = build_profile_review_recap_bytes(req.review)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to build report: {e}")

    return Response(
        content=docx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": 'attachment; filename="Spotlight_Report.docx"'},
    )


@app.post("/api/prepare")
async def api_prepare(
    job_description: str = Form(""),
    resume_file: UploadFile = File(default=None),
):
    job_description = job_description.strip()
    if not job_description:
        raise HTTPException(status_code=400, detail="Please paste the job description.")
    if len(job_description) < MIN_JOB_DESCRIPTION_CHARS:
        raise HTTPException(
            status_code=400,
            detail="That job description looks too short to work with — please paste the full posting.",
        )
    if len(job_description) > MAX_JOB_DESCRIPTION_CHARS:
        raise HTTPException(
            status_code=400,
            detail=f"That job description is too long ({len(job_description)} characters, {MAX_JOB_DESCRIPTION_CHARS} max) — please paste just the posting text.",
        )

    resume_text = ""
    if resume_file is not None:
        content = await resume_file.read()
        if len(content) > MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="That resume file is too large (5 MB max).")
        try:
            resume_text = extract_text(resume_file.filename, content)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        if not resume_text.strip():
            raise HTTPException(status_code=400, detail="Could not extract any text from that resume file.")

    try:
        result = await run_in_threadpool(prepare, job_description, resume_text)
    except PrepareError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Unexpected error: {type(e).__name__}: {e}")

    return result


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
        result = await run_in_threadpool(
            draft_entry, req.entry_type, req.title, req.organization, req.dates, req.description
        )
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
        result = await run_in_threadpool(finalize, req.name, req.experience, req.education, req.existing_skills)
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
