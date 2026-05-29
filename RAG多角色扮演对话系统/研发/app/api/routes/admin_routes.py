from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from app.api.auth import require_admin
from app.api.schemas import UserAdminUpdateRequest
from app.api.state import append_knowledge_base, refresh_knowledge_base
from app.core.blocking import run_blocking
from app.repositories.database import delete_user, list_users, update_user_admin
from app.services.knowledge_manager import (
    list_uploaded_files,
    load_registered_documents,
    save_uploaded_file,
)


router = APIRouter()


@router.get("/api/admin/users")
async def api_list_users(current_user: dict = Depends(require_admin)):
    del current_user
    return await run_blocking(list_users)


@router.patch("/api/admin/users/{user_id}")
async def api_update_user_admin(
    user_id: int,
    request: UserAdminUpdateRequest,
    current_user: dict = Depends(require_admin),
):
    result = await run_blocking(update_user_admin, user_id, request.is_admin, current_user["id"])
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["message"])
    return result


@router.delete("/api/admin/users/{user_id}")
async def api_delete_user(user_id: int, current_user: dict = Depends(require_admin)):
    result = await run_blocking(delete_user, user_id, current_user["id"])
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["message"])
    return result


@router.get("/api/admin/data/files")
async def api_list_data_files(current_user: dict = Depends(require_admin)):
    del current_user
    return await run_blocking(list_uploaded_files)


@router.post("/api/admin/data/reload")
async def api_reload_data(current_user: dict = Depends(require_admin)):
    del current_user
    try:
        summary = await run_blocking(refresh_knowledge_base)
        return {
            "success": True,
            "message": "知识库重建成功",
            **summary,
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/api/admin/data/upload")
async def api_upload_data_file(
    file: UploadFile = File(...),
    target_role: str = Form(""),
    knowledge_scope: str = Form("shared"),
    import_mode: str = Form("incremental"),
    current_user: dict = Depends(require_admin),
):
    del current_user

    if not file.filename:
        raise HTTPException(status_code=400, detail="请选择要上传的文件")

    try:
        raw = await file.read()
        if not raw:
            raise HTTPException(status_code=400, detail="上传文件不能为空")

        upload_result = await run_blocking(
            save_uploaded_file,
            raw=raw,
            original_name=file.filename,
            knowledge_scope=knowledge_scope,
            import_mode=import_mode,
            target_role=target_role,
        )
        if upload_result.get("import_mode") == "incremental":
            summary = await run_blocking(
                append_knowledge_base,
                documents=upload_result.get("records", []),
                loaded_files=[upload_result["entry"]],
            )
        else:
            documents = await run_blocking(
                load_registered_documents,
                manifest_entries=upload_result.get("entries", []),
            )
            summary = await run_blocking(
                refresh_knowledge_base,
                documents=documents,
                loaded_files=upload_result.get("entries", []),
            )
        entry = upload_result["entry"]
        return {
            "success": True,
            "message": "数据文件上传并重建知识库成功",
            "saved_name": entry["saved_name"],
            "original_name": entry["original_name"],
            "knowledge_scope": entry["knowledge_scope"],
            "target_role": entry["target_role"],
            "import_mode": upload_result["import_mode"],
            "removed_count": upload_result["removed_count"],
            **summary,
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        await file.close()
