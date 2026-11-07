from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel

from shutong.api.auth import COOKIE, SESSION_SECONDS

router = APIRouter(prefix="/api/auth", tags=["auth"])


class Password(BaseModel):
    password: str


class PasswordChange(BaseModel):
    old: str
    new: str


class AuthStatus(BaseModel):
    configured: bool
    logged_in: bool
    desktop: bool = False


class Ok(BaseModel):
    ok: bool = True


def _start_session(request: Request, response: Response) -> None:
    response.set_cookie(COOKIE, request.app.state.auth.issue(), max_age=SESSION_SECONDS, httponly=True,
                        samesite="lax")


@router.get("/status", response_model=AuthStatus)
def status(request: Request) -> AuthStatus:
    auth = request.app.state.auth
    return AuthStatus(configured=auth.configured, logged_in=auth.valid(request.cookies.get(COOKIE)),
                      desktop=request.app.state.desktop)


@router.post("/setup", response_model=Ok)
def setup(body: Password, request: Request, response: Response) -> Ok:
    auth = request.app.state.auth
    if auth.configured:
        raise HTTPException(409, "密码已设置")
    auth.set_password(body.password)
    _start_session(request, response)
    return Ok()


@router.post("/login", response_model=Ok)
def login(body: Password, request: Request, response: Response) -> Ok:
    if not request.app.state.auth.verify(body.password):
        raise HTTPException(401, "密码错误")
    _start_session(request, response)
    return Ok()


@router.post("/logout", response_model=Ok)
def logout(response: Response) -> Ok:
    response.delete_cookie(COOKIE)
    return Ok()


@router.post("/password", response_model=Ok)
def change_password(body: PasswordChange, request: Request, response: Response) -> Ok:
    auth = request.app.state.auth
    if not auth.valid(request.cookies.get(COOKIE)):
        raise HTTPException(401, "未登录")
    if not auth.verify(body.old):
        raise HTTPException(401, "密码错误")
    auth.set_password(body.new)
    _start_session(request, response)
    return Ok()
