"""Private persistent image storage for the hosted app."""
from pathlib import Path
from . import cloud_database

APP_DIR = Path(__file__).resolve().parent


def _key(path): return Path(path).resolve().relative_to(APP_DIR).as_posix()


def write(path, payload):
    if cloud_database.enabled():
        with cloud_database.connection() as con:
            con.execute("INSERT INTO file_objects(object_key,content) VALUES(?,?) ON CONFLICT(object_key) DO UPDATE SET content=excluded.content",(_key(path),payload))
    else: Path(path).write_bytes(payload)


def read(path):
    if cloud_database.enabled():
        with cloud_database.connection() as con:
            row=con.execute("SELECT content FROM file_objects WHERE object_key=?",(_key(path),)).fetchone()
        if not row: raise FileNotFoundError("Stored image not found")
        return bytes(row[0])
    return Path(path).read_bytes()


def exists(path):
    if cloud_database.enabled():
        with cloud_database.connection() as con:
            return bool(con.execute("SELECT 1 FROM file_objects WHERE object_key=?",(_key(path),)).fetchone())
    return Path(path).is_file()


def delete(path):
    if cloud_database.enabled():
        with cloud_database.connection() as con:
            con.execute("DELETE FROM file_objects WHERE object_key=?",(_key(path),))
    else: Path(path).unlink(missing_ok=True)


def display_bytes(path):
    payload=read(path)
    if len(payload)>4_000_000:
        import io
        from PIL import Image
        image=Image.open(io.BytesIO(payload)).convert("RGB")
        image.thumbnail((1600,1600))
        out=io.BytesIO();image.save(out,"JPEG",quality=90)
        return out.getvalue(),"image/jpeg"
    return payload,{".jpg":"image/jpeg",".jpeg":"image/jpeg",".png":"image/png",".webp":"image/webp"}[Path(path).suffix.lower()]
