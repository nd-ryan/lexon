from fastapi import APIRouter, UploadFile, File, HTTPException, Depends
from sqlalchemy.orm import Session
from app.lib.security import get_api_key
from app.lib.db import get_db
from app.lib.case_repo import case_repo
import tempfile
import os
import logging


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/cases", dependencies=[Depends(get_api_key)])


@router.post("/upload")
async def upload_case(file: UploadFile = File(...), db: Session = Depends(get_db)):
    tmp_path = None
    try:
        file_bytes = await file.read()
        with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(file.filename)[1] or ".docx") as tmp:
            tmp.write(file_bytes)
            tmp_path = tmp.name

        # Create case record
        case_id = case_repo.create_case(db.connection(), file.filename)

        # Run extraction flow (placeholder flow class to be added)
        from app.flow_cases import CaseExtractFlow  # type: ignore
        flow = CaseExtractFlow()
        flow.state.file_path = tmp_path
        flow.state.filename = file.filename
        flow.state.case_id = case_id

        result = await flow.kickoff_async()
        case_repo.save_extraction(db.connection(), case_id, result)

        db.commit()
        return {"success": True, "caseId": case_id}
    except Exception as e:
        logger.exception("Case upload failed")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except Exception:
                pass


@router.get("")
def list_cases(limit: int = 50, offset: int = 0, db: Session = Depends(get_db)):
    items = case_repo.list_cases(db.connection(), q=None, limit=limit, offset=offset)
    return {"success": True, "items": items}


@router.get("/{case_id}")
def get_case(case_id: str, db: Session = Depends(get_db)):
    data = case_repo.get_case(db.connection(), case_id)
    if not data:
        raise HTTPException(404, "Not found")
    return {"success": True, "case": data}


@router.put("/{case_id}")
def update_case(case_id: str, payload: dict, db: Session = Depends(get_db)):
    user_id = "editor"  # TODO: integrate auth user
    updated = case_repo.update_case(db.connection(), case_id, payload, user_id)
    db.commit()
    return {"success": True, "case": updated}


