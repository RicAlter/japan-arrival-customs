import json
from .cli import main
if __name__=='__main__':
    try:main()
    except Exception as exc:
        print(json.dumps({'status':'blocked','reason':str(exc),'positions':getattr(exc,'positions',[])},ensure_ascii=False));raise SystemExit(1)
