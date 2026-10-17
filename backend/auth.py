"""Auth: OIDC bearer-token validation when AUTH_MODE=oidc, otherwise a dev user.
Point OIDC_ISSUER at Entra ID / Okta / Keycloak; the JWKS is fetched and cached.
"""
import os, time, httpx
from fastapi import Header, HTTPException
from jose import jwt

AUTH_MODE = os.getenv("AUTH_MODE", "dev")
ISSUER = os.getenv("OIDC_ISSUER", "")
AUDIENCE = os.getenv("OIDC_AUDIENCE", "dc-aiops")
_jwks = {"keys": None, "at": 0}

async def _keys():
    if _jwks["keys"] and time.time() - _jwks["at"] < 3600: return _jwks["keys"]
    async with httpx.AsyncClient(timeout=5) as c:
        cfg = (await c.get(f"{ISSUER.rstrip('/')}/.well-known/openid-configuration")).json()
        _jwks["keys"] = (await c.get(cfg["jwks_uri"])).json(); _jwks["at"] = time.time()
    return _jwks["keys"]

async def current_user(authorization: str = Header(default="")):
    mode = os.getenv("AUTH_MODE", AUTH_MODE)
    if mode != "oidc":
        return {"sub": "dev", "name": "dev-operator", "roles": ["operator", "shift-lead"]}
    if not authorization.startswith("Bearer "): raise HTTPException(401, "missing bearer token")
    try:
        claims = jwt.decode(authorization[7:], await _keys(), audience=AUDIENCE, issuer=ISSUER)
    except Exception as e:
        raise HTTPException(401, f"invalid token: {e}")
    return {"sub": claims["sub"], "name": claims.get("name", claims["sub"]),
            "roles": claims.get("roles", [])}
