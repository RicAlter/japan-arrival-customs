"""Explicit test-only child: terminate during a private A-03 Store commit."""
import os
import sys
from a_confirm.service import Service

service=Service(sys.argv[1])
from arrival_core import storage
original=storage.atomic_json


def terminate(file,value):
    if file.name=='head.json':
        if sys.argv[3]=='before':os._exit(71)
        original(file,value);os._exit(72)
    return original(file,value)


storage.atomic_json=terminate
service.commit(sys.argv[2],confirmed_hash=sys.argv[2],explicit_confirmation=True,reference='TEST:real process termination')
