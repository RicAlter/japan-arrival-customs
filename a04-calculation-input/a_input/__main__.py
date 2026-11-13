import argparse
import json
from .bridge import Bridge

p = argparse.ArgumentParser(description='A04只读接入与计算前检查，不生成Excel')
p.add_argument('--root', required=True)
p.add_argument('--batch-id', required=True)
a = p.parse_args()
print(json.dumps(Bridge(a.root).prepare(a.batch_id), ensure_ascii=False, indent=2))
