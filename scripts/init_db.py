from backend.config import Config
from backend.database import Database


if __name__ == "__main__":
    database = Database(Config.DATABASE_PATH)
    database.init()
    print(f"Initialized database at {Config.DATABASE_PATH}")
