import hashlib
import time
from typing import Optional
from fastapi import Security, HTTPException, Depends
from fastapi.security.api_key import APIKeyHeader, APIKeyQuery
from sqlalchemy.orm import Session

from src.database import get_db
from src.models.db_models import ApiKey

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)
# Fallback por query param (?api_key=...) para páginas que se abren en el
# navegador (dashboard /admin/review), donde no se pueden mandar headers custom.
api_key_query = APIKeyQuery(name="api_key", auto_error=False)

def hash_api_key(api_key: str) -> str:
    return hashlib.sha256(api_key.encode()).hexdigest()

class RequireKey:
    def __init__(self, required_scope: str):
        self.required_scope = required_scope

    def __call__(
        self,
        api_key_header: Optional[str] = Security(api_key_header),
        api_key_query: Optional[str] = Security(api_key_query),
        db: Session = Depends(get_db),
    ):
        provided_key = api_key_header or api_key_query
        if not provided_key:
            raise HTTPException(status_code=401, detail="X-API-Key header missing")

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
