import json
from .runtime import cli
if __name__=='__main__':
    try:cli.main()
    except Exception as exc:print(json.dumps({'status':'blocked','reason':str(exc)},ensure_ascii=False));raise SystemExit(1)
