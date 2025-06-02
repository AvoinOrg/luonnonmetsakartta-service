from fastapi import HTTPException, Security, status
from fastapi.security import OAuth2PasswordBearer

from app.auth.validator import ZitadelIntrospectTokenValidator, ValidatorError
from app.utils.logger import get_logger
from app.config import get_settings

settings = get_settings()

logger = get_logger(__name__)

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token", auto_error=True)
oauth2_scheme_optional = OAuth2PasswordBearer(tokenUrl="token", auto_error=False)


async def get_scope_status(scopes: list[str], token: str = Security(oauth2_scheme)):
    validator = ZitadelIntrospectTokenValidator()
    user_id = None

    try:
        data = validator.introspect_token(token)
        validator.validate_token(data, scopes=scopes)
        user_id = data.get("sub")
    except ValidatorError as ex:
        raise HTTPException(status_code=ex.status_code, detail=ex.error)

    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # if all scopes are in the token, return True
    return True


async def get_editor_status(token: str = Security(oauth2_scheme)):
    result = await get_scope_status([settings.zitadel_project_editor_role], token)
    return {"is_editor": result}


async def get_editor_status_optional(token: str = Security(oauth2_scheme_optional)):
    editor_status = {"is_editor": False}
    try:
        editor_status = await get_editor_status(token)
    except Exception as e:
        logger.error(e)
        pass
    finally:
        return editor_status


# async def get_admin_status(token: str = Security(oauth2_scheme)):
#     result = await get_scope_status([settings.zitadel_project_admin_role], token)
#     return {"is_admin": result}


# async def get_current_user(token: str = Security(oauth2_scheme)):
#     validator = ZitadelIntrospectTokenValidator()
#     user_id = None

#     try:
#         data = validator.introspect_token(token)
#         logger.error(data)
#         validator.validate_token(data, "")
#         user_id = data.get("sub")
#     except ValidatorError as ex:
#         raise HTTPException(status_code=ex.status_code, detail=ex.error)

#     if user_id is None:
#         raise HTTPException(
#             status_code=status.HTTP_401_UNAUTHORIZED,
#             detail="Could not validate credentials",
#             headers={"WWW-Authenticate": "Bearer"},
#         )
#     return {"user_id": user_id}

# async def get_current_user_optional(token: str = Security(oauth2_scheme_optional)):
#     if not token:
#         return None
#     try:
#         res = await get_current_user(token)
#         return res
#     except HTTPException as e:
#         return None
