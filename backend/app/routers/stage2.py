from fastapi import APIRouter, File, Form, UploadFile

from ..models.schemas import ResumeCheckResponse, ResumeSaveRequest, ResumeSaveResponse
from ..exceptions import ResumeValidationError, ResumeNotFoundError

router = APIRouter(prefix="/api/v1/resume", tags=["stage2"])

@router.post("/check", response_model=ResumeCheckResponse)
async def resume_check(
    resume_id: str = Form(None),
    resume_file: UploadFile = File(None),
    jd_text: str = Form(...),
) -> ResumeCheckResponse:
    from ..services import resume_store
    from ..services.ats_checker import check_resume

    saved_path = None

    if resume_file:
        content = await resume_file.read()
        if not content:
            raise ResumeValidationError("Uploaded resume is empty")

        resume_id, saved_path = resume_store.store_upload(
            content, resume_file.filename or "resume",
        )

        # Parse and persist the upload for later use
        from ..services.resume_parser import parse_resume
        import tempfile, os
        suffix = os.path.splitext(resume_file.filename or "")[1] or ".pdf"
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(content)
            tmp_path = tmp.name
        try:
            parsed = parse_resume(tmp_path)
            resume_store.save_parsed(resume_id, parsed)
        finally:
            os.unlink(tmp_path)
    elif resume_id:
        saved_path = resume_store.original_file_path(resume_id)
        if not saved_path:
            raise ResumeNotFoundError(resume_id)
    else:
        raise ResumeValidationError("Either resume_file or resume_id must be provided.")

    return await check_resume(str(saved_path), jd_text, resume_id=resume_id)

@router.post("/save", response_model=ResumeSaveResponse)
async def resume_save(request: ResumeSaveRequest) -> ResumeSaveResponse:
    from ..services.resume_saver import save_resume
    return await save_resume(
        resume_id=request.resume_id,
        accepted_suggestions=request.accepted_suggestions,
        mode=request.mode,
        confirm_overwrite=request.confirm_overwrite,
    )
