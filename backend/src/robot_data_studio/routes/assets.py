from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field

from robot_data_contracts.asset import AssetArtifact, AssetDraft
from ..services.asset_service import AssetRegistry, AssetConflict, AssetNotFound, AssetIntegrityError

from ..services.validation_overview import validation_overview
from ..services.cloth_run_service import cloth_run_manager, newton_cloth_run_manager

router = APIRouter(tags=["assets"])


class PublishRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    draft: AssetDraft
    expected_version: int = Field(default=0, ge=0)


class ClothRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    asset_id: str
    version: int = Field(ge=1)
    scenario: str | None = None
    material_id: str = "medium"
    material_overrides: dict = Field(default_factory=dict)
    solver_overrides: dict = Field(default_factory=dict)


def failure(error):
    code = 409 if isinstance(error, AssetConflict) else 404 if isinstance(error, AssetNotFound) else 422
    return HTTPException(code, str(error))


@router.get("/assets")
def index(q: str = Query("", max_length=200), kind: str = "", engine: str = "", outcome: str = "", integrity: str = "",
          offset: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=250)):
    try:
        return AssetRegistry().catalog(q, kind, engine, outcome, integrity, offset, limit)
    except (OSError, ValueError) as error:
        raise failure(error) from error


@router.get("/assets/validation-overview")
def overview():
    try:
        return validation_overview(AssetRegistry())
    except (OSError, ValueError) as error:
        raise failure(error) from error


@router.get("/assets/sources")
def sources():
    return AssetRegistry().sources()


@router.post("/assets/artifacts/inspect")
def inspect(artifact: AssetArtifact):
    try:
        return AssetRegistry().inspect_artifact(artifact)
    except (OSError, ValueError) as error:
        raise failure(error) from error


@router.post("/assets", status_code=201)
def publish(request: PublishRequest):
    try:
        record, created = AssetRegistry().publish(request.draft, request.expected_version)
        return {"record": record, "created": created}
    except (OSError, ValueError) as error:
        raise failure(error) from error


@router.post("/assets/runs", status_code=202)
def start_cloth_run(request: ClothRunRequest):
    try:
        selected = AssetRegistry().get(request.asset_id, request.version)
        if "clothforge" in selected.tags and "newton_vbd" in selected.engines:
            return newton_cloth_run_manager.start(
                request.asset_id, request.version, scenario=request.scenario or selected.data.get("scenario", "hanging"),
                material_id=request.material_id, material_overrides=request.material_overrides,
                solver_overrides=request.solver_overrides)
        if request.scenario is not None or request.material_overrides or request.solver_overrides or request.material_id != "medium":
            raise ValueError("tuning parameters are only supported by ClothForge")
        return cloth_run_manager.start(request.asset_id, request.version)
    except (OSError, ValueError) as error:
        raise failure(error) from error


@router.get("/assets/runs/{run_id}")
def cloth_run(run_id: str):
    try:
        return newton_cloth_run_manager.get(run_id)
    except (OSError, ValueError) as error:
        raise failure(error) from error


@router.get("/assets/{asset_id}/cloth-options")
def cloth_options(asset_id: str, version: int = Query(ge=1)):
    try:
        return newton_cloth_run_manager.options(asset_id, version)
    except (OSError, ValueError) as error:
        raise failure(error) from error


@router.get("/assets/{asset_id}")
def detail(asset_id: str, version: int | None = Query(None, ge=1)):
    try:
        return AssetRegistry().detail(asset_id, version)
    except (OSError, ValueError) as error:
        raise failure(error) from error


@router.get("/assets/{asset_id}/versions/{version}/artifacts/{index}")
def artifact(asset_id: str, version: int, index: int):
    try:
        registry = AssetRegistry()
        record = registry.get(asset_id, version)
        if index < 0 or index >= len(record.artifacts):
            raise AssetNotFound("artifact index does not exist")
        entry = record.artifacts[index]
        registry.inspect_artifact(entry)
        path = registry.artifact_path(entry)
        suffix = path.suffix.lower()
        if entry.role == "video" and suffix in (".mp4", ".webm"):
            return FileResponse(path, media_type="video/mp4" if suffix == ".mp4" else "video/webm",
                                headers={"X-Content-Type-Options": "nosniff"})
        image_types = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}
        if entry.role == "preview" and suffix in image_types:
            return FileResponse(path, media_type=image_types[suffix], headers={"X-Content-Type-Options": "nosniff"})
        return FileResponse(path, media_type="application/octet-stream", filename=path.name, headers={"X-Content-Type-Options": "nosniff"})
    except (OSError, ValueError) as error:
        raise failure(error) from error


@router.get("/assets/{asset_id}/versions/{version}/artifacts/{index}/viewer")
def viewer(asset_id: str, version: int, index: int):
    try:
        registry = AssetRegistry()
        record = registry.get(asset_id, version)
        if index < 0 or index >= len(record.artifacts):
            raise AssetNotFound("artifact index does not exist")
        entry = record.artifacts[index]
        if (entry.role not in {"interactive_preview", "interactive_replay"}
                or entry.source_id not in {"clothforge-pilot-v1", "clothforge-repair-v2", "studio-cloth-runs"}):
            raise ValueError("artifact is not an interactive cloth viewer")
        if registry.integrity(record)["status"] != "current":
            raise AssetIntegrityError("viewer evidence is stale")
        path = registry.artifact_path(registry.inspect_artifact(entry))
        if path.suffix.lower() != ".html":
            raise ValueError("unsupported viewer type")
        return FileResponse(path, media_type="text/html", headers={
            "X-Content-Type-Options": "nosniff", "Cache-Control": "no-store",
            "Content-Security-Policy": "sandbox allow-scripts; default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'",
            "Referrer-Policy": "no-referrer",
        })
    except (OSError, ValueError) as error:
        raise failure(error) from error
