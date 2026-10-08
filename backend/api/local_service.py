"""本机服务端口偏好与显式退出入口，不返回启动器实例令牌。"""
from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from pydantic import BaseModel, Field

from backend.local_service import LauncherPreferences, LauncherPreferencesError, read_preferences, save_preferences


router = APIRouter(prefix="/local-service", tags=["本地服务"])


class LocalServiceInput(LauncherPreferences):
    preferred_port: int = Field(ge=1024, le=65535, strict=True)


class LocalServiceView(BaseModel):
    port: int
    page_port: int
    can_stop: bool
    preferred_port: int
    desktop_window: bool = False


class LocalServiceStopView(BaseModel):
    stopping: bool
    message: str


def _preferences(request: Request) -> LauncherPreferences:
    if request.app.state.local_service_database == ":memory:":
        return request.app.state.local_service_preferences
    try:
        return read_preferences(request.app.state.local_service_database)
    except LauncherPreferencesError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None


def _view(request: Request, preferences: LauncherPreferences) -> LocalServiceView:
    port = request.url.port or 80
    return LocalServiceView(
        port=port,
        page_port=getattr(request.app.state, "local_service_page_port", None) or port,
        can_stop=callable(getattr(request.app.state, "local_service_stop", None)),
        preferred_port=preferences.preferred_port,
        desktop_window=bool(getattr(request.app.state, "local_service_desktop_window", False)),
    )


@router.get("", response_model=LocalServiceView)
def get_local_service(request: Request):
    return _view(request, _preferences(request))


@router.put("", response_model=LocalServiceView)
def update_local_service(body: LocalServiceInput, request: Request):
    if request.app.state.local_service_database == ":memory:":
        request.app.state.local_service_preferences = body
    else:
        try:
            save_preferences(body, request.app.state.local_service_database)
        except LauncherPreferencesError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from None
    return _view(request, body)


@router.post("/stop", response_model=LocalServiceStopView)
def stop_local_service(request: Request, background_tasks: BackgroundTasks):
    stop = getattr(request.app.state, "local_service_stop", None)
    if not callable(stop):
        raise HTTPException(status_code=409, detail="当前启动方式不支持从网页关闭，请回到启动终端按 Ctrl+C。")
    background_tasks.add_task(stop)
    return LocalServiceStopView(stopping=True, message="正在关闭本地服务，重新双击轻记.exe 可再次启动。")
