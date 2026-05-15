import sys
sys.path.insert(0, '/app')
try:
    from app.api.v1 import router
    print("router loaded OK")
    for r in router.routes:
        print(r.path)
except Exception as e:
    print(f"FAILED: {e}")

try:
    from app.main import app
    print("app routes:")
    for r in app.routes:
        print(getattr(r, 'path', str(r)))
except Exception as e:
    print(f"app import FAILED: {e}")
