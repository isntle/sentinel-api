import pytest
import time
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient
from main import app
from src.database import get_db, Base, engine
from sqlalchemy.orm import Session
from src.models.db_models import ApiKey
from src.core.security import hash_api_key

# We override the DB dependency for tests
@pytest.fixture(scope="session")
def db_session():
    Base.metadata.create_all(bind=engine)
    db = next(get_db())
    yield db
    # We do not drop tables because other things might be running, but in a real isolated test we would.

@pytest.fixture(scope="session")
def client():
    return TestClient(app)

@pytest.fixture
def client_key(db_session: Session):
    key = "test_client_key"
    key_hash = hash_api_key(key)
    
    existing = db_session.query(ApiKey).filter(ApiKey.key_hash == key_hash).first()
    if not existing:
        ak = ApiKey(key_hash=key_hash, name="Test Client", scope="client", created_at=int(time.time()))
        db_session.add(ak)
        db_session.commit()
        
    return key

@pytest.fixture
def admin_key(db_session: Session):
    key = "test_admin_key"
    key_hash = hash_api_key(key)
    
    existing = db_session.query(ApiKey).filter(ApiKey.key_hash == key_hash).first()
    if not existing:
        ak = ApiKey(key_hash=key_hash, name="Test Admin", scope="admin", created_at=int(time.time()))
        db_session.add(ak)
        db_session.commit()
        
    return key


def test_no_api_key_rejected(client):
    response = client.get("/api/v1/hot-terms")
    assert response.status_code == 401
    assert "missing" in response.json()["detail"].lower()

def test_client_key_accepted_on_client_route(client, client_key):
    response = client.get("/api/v1/hot-terms", headers={"X-API-Key": client_key})
    assert response.status_code == 200

def test_client_key_rejected_on_admin_route(client, client_key):
    # /api/v1/admin/scrape requires admin key
    response = client.post("/api/v1/admin/scrape", headers={"X-API-Key": client_key})
    assert response.status_code == 403
    assert "Not enough permissions" in response.json()["detail"]

def test_admin_key_accepted_on_admin_route(client, admin_key):
    # using get /api/v1/hot-terms/pipeline-stats which is admin
    response = client.get("/api/v1/hot-terms/pipeline-stats", headers={"X-API-Key": admin_key})
    assert response.status_code == 200

def test_admin_key_accepted_on_client_route(client, admin_key):
    # Admin should also be able to access client routes if they use the client dependency,
    # because admin scope check in RequireKey is only for required_scope="admin".
    # Wait, our RequireKey logic currently only checks: 
    # if required == admin and scope != admin -> 403. 
    # This means admin CAN access client endpoints because required == client, and it doesn't fail.
    response = client.get("/api/v1/hot-terms", headers={"X-API-Key": admin_key})
    assert response.status_code == 200
