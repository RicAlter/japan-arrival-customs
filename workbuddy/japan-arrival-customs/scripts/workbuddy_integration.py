"""Run this synthetic CLI scenario in WorkBuddy; native-trigger evidence is collected separately."""
import argparse
import hashlib
import json
import platform
import subprocess
import sys
from pathlib import Path

from arrival_core.core import digest, new_batch, new_row
from arrival_core.storage import Store, atomic_json


def main():
    parser=argparse.ArgumentParser(description="最终集中合成集成验收，不使用真实商品或正式报单")
    parser.add_argument("--output",required=True)
    parser.add_argument("--operator-session",required=True,help="实际WorkBuddy会话/运行标识；标识本身不证明原生触发")
    parser.add_argument("--context",choices=("workbuddy","local-rehearsal"),required=True)
    parser.add_argument("--renderer-runtime",help="可选旧Node适配器；默认只用Python/openpyxl生成及重读双表")
    args=parser.parse_args()
    root=Path(args.output).resolve()
    if root.exists():raise SystemExit("测试目录已存在，使用新的独立目录，不覆盖旧证据")
    inputs=root/"synthetic_inputs";inputs.mkdir(parents=True)
    source=inputs/"synthetic_stage3_source.json"
    atomic_json(source,{"synthetic_only":True,"amounts":["10","20","30"],"currency":"JPY"})
    h=hashlib.sha256(source.read_bytes()).hexdigest()
    rows=[]
    for i,name in enumerate(("N1","N2","D1"),1):
        origin={"path":str(source),"sha256":h,"sheet":"synthetic-stage3","row":i,"stage":3}
        row=new_row(origin,{"code":"SYNTHETIC-"+name,"internal":"合成内部名称"+name,"amount":str(i*10),"qty":"1","category":"合成测试类别"},currency="JPY",quantity_unit="件")
        row["product"].update(customs_name="合成申报测试商品",frontend_status="absent",frontend_absence_reason="合成无前台样例",yd_absence_reason="合成无YD样例")
        if name=="D1":row["disputes"]=[{"id":"D1","domain":"product","reason":"合成商品身份多候选，不得误批"}]
        rows.append(row)
    batch=new_batch(rows,[{"path":str(source),"sha256":h,"stage":3}])
    store=Store(root/"state");folder=store.save(batch)
    permissions=root/"synthetic_permissions.json"
    atomic_json(permissions,{"合成测试审核人":["business"]})
    def run(*arguments):
        result=subprocess.run([sys.executable,"-X","utf8",str(Path(__file__).with_name("run.py")),"--output",str(store.root),*arguments],capture_output=True,text=True,encoding="utf-8")
        return result
    package_result=run("review-package","--batch",batch["id"])
    if package_result.returncode:raise RuntimeError(package_result.stdout+package_result.stderr)
    package=json.loads(Path(json.loads(package_result.stdout)["file"]).read_text(encoding="utf-8"))
    def fingerprint():return {p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in folder.glob("*.json")}
    before=fingerprint()
    request=root/"D1_mixed_batch_request.json"
    common={"state_hash":digest(batch),"actor":"合成测试审核人","evidence":"P1-B合成测试，不是真实业务签核","action":"confirm-products","package":package,"mode":"batch"}
    atomic_json(request,{**common,"row_ids":[r["id"] for r in rows]})
    failed=run("apply","--batch",batch["id"],"--request",str(request),"--permissions",str(permissions))
    after=fingerprint()
    atomic_json(root/"D1_rejection_process.json",{"returncode":failed.returncode,"stdout":failed.stdout,"stderr":failed.stderr,
                "before_files":before,"after_files":after,"state_hash_before":digest(batch),"state_hash_after":digest(store.load(batch["id"]))})
    if failed.returncode!=2 or before!=after:raise RuntimeError("D1应整次拒绝且状态不变，测试失败")
    normal=root/"ordinary_batch_request.json"
    atomic_json(normal,{**common,"row_ids":[r["id"] for r in rows[:2]]})
    passed=run("apply","--batch",batch["id"],"--request",str(normal),"--permissions",str(permissions))
    if passed.returncode:raise RuntimeError(passed.stdout+passed.stderr)
    updated=store.load(batch["id"])
    if not all(r["reviews"]["product"] for r in updated["rows"][:2]) or updated["rows"][2]["reviews"]["product"] is not None:
        raise RuntimeError("普通项与D1确认范围异常")
    render_args=["render-drafts","--batch",batch["id"]]
    if args.renderer_runtime:render_args += ["--runtime",str(Path(args.renderer_runtime).resolve())]
    rendered=run(*render_args)
    atomic_json(root/"renderer_process.json",{"returncode":rendered.returncode,"stdout":rendered.stdout,"stderr":rendered.stderr})
    if rendered.returncode:raise RuntimeError("双表生成重读验证失败: "+rendered.stdout+rendered.stderr)
    renderer_status="synthetic_pair_rendered_and_reopened_display_pending_human_review"
    receipt={"synthetic_only":True,"declared_execution_context":args.context,"operator_session":args.operator_session,
        "python":sys.executable,"python_version":platform.python_version(),"platform":platform.platform(),
        "skill_entry_sha256":hashlib.sha256((Path(__file__).resolve().parent.parent/"SKILL.md").read_bytes()).hexdigest(),
        "D1_program_rejected_and_state_unchanged":True,"ordinary_N1_N2_confirmed":True,"D1_still_pending":True,
        "native_trigger_status":"requires_UI_or_original_skill_tool_call_evidence",
        "renderer_test":renderer_status,
        "WorkBuddy_integration_gate":"pending_human_evidence_review",
        "warning":"此回执不能单独证明Skill原生触发；local-rehearsal不能充当WorkBuddy实机证据"}
    atomic_json(root/"integration_receipt.json",receipt)
    print(json.dumps({"receipt":str(root/"integration_receipt.json"),**receipt},ensure_ascii=False))


if __name__=="__main__":main()
