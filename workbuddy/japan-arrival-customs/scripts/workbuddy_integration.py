"""Compatibility notice for the obsolete self-declared-identity rehearsal.

The frozen 0.6.0 script/evidence are unchanged. This 0.7.0 copy must not create
synthetic permissions or treat a caller's operator/context labels as identity.
"""

def main():
    raise SystemExit('旧无可信身份预演已停用。请按references/v070-operation.md通过同一run.py执行可信宿主配置→合同填写签核→Excel回传→D1→双草稿；历史证据保留，不用于rc.3身份验收。')


if __name__=='__main__':main()
