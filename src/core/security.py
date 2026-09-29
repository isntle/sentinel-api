import hashlib
import time
from typing import Optional
from fastapi import Security, HTTPException, Depends
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.security.api_key import APIKeyHeader
from sqlalchemy.orm import Session

from src.database import get_db
from src.models.db_models import ApiKey

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)
basic_auth = HTTPBasic(auto_error=False)

def hash_api_key(api_key: str) -> str:
    return hashlib.sha256(api_key.encode()).hexdigest()

class RequireKey:
    def __init__(self, required_scope: str):
        self.required_scope = required_scope

    def __call__(
        self,
        api_key_header: Optional[str] = Security(api_key_header),
        basic_credentials: Optional[HTTPBasicCredentials] = Security(basic_auth),
        db: Session = Depends(get_db),
    ):
        # Basic auth permite abrir el dashboard sin poner secretos en la URL.
        # El usuario es descriptivo; la contraseña contiene la API key admin.
        provided_key = api_key_header or (
            basic_credentials.password if basic_credentials else None
        )
        if not provided_key:
            headers = (
                {"WWW-Authenticate": 'Basic realm="Sentinel Admin"'}
                if self.required_scope == "admin"
                else None
            )
            raise HTTPException(
                status_code=401,
                detail="X-API-Key header missing",
                headers=headers,
            )

        key_hash = hash_api_key(provided_key)
        db_key = db.query(ApiKey).filter(ApiKey.key_hash == key_hash).first()
        
        if not db_key:
            raise HTTPException(status_code=401, detail="Invalid API Key")
            
        if db_key.revoked_at is not None:
            raise HTTPException(status_code=401, detail="API Key has been revoked")
            
        # Admin keys can access everything. Client keys only client scope.
        if self.required_scope == "admin" and db_key.scope != "admin":
            raise HTTPException(status_code=403, detail="Not enough permissions")
            
        # Update last used
        db_key.last_used_at = int(time.time())
        db.commit()
        
        return db_key

# Conveniences
require_client_key = RequireKey(required_scope="client")
require_admin_key = RequireKey(required_scope="admin")
