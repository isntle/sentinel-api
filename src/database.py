from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

# Nombre del archivo de la base de datos
SQLALCHEMY_DATABASE_URL = "sqlite:///./sentinel.db"

# El motor (engine) se encarga de la conexión física
engine = create_engine(
    SQLALCHEMY_DATABASE_URL, 
    connect_args={"check_same_thread": False} # Requerido para SQLite y FastAPI
)

# Sesión local para interactuar con la DB
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Clase base de la que heredarán todos los modelos de tablas
Base = declarative_base()

# Función (Dependency Injection) para obtener la sesión de DB en las rutas
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
