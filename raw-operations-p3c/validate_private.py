"""Local historical acceptance. Private paths, sources and reports stay local.

The answer is opened only after preparation and unconfirmed math are finished
and hashed. No answer-derived value returns to the bridge or original engine.
"""
import argparse
from collections import defaultdict
from fractions import Fraction
from pathlib import Path
import sys

sys.dont_write_bytecode=True
from raw_operations.bridge import execute,bootstrap,load,save,digest,key,check_hashes


def validate(config):
    root=Path(config['report']).resolve();root.mkdir(parents=True,exist_ok=False)
    protected=dict(config['protected_files']);check_hashes(protected)
    request={k:config[k] for k in ('batch_id','raw_file','business_file','declaration_file','library_config')}
    protected.update({str(Path(config[k]).resolve()):digest(config[k]) for k in ('raw_file','business_file','declaration_file','answer_customs')})
    protected[config['library_config']['database']]=digest(config['library_config']['database'])
    save(root/'protected-before.json',protected)
    output=Path(config['output']).resolve();result=execute(output,request)
    save(root/'bridge-result.json',result)
    if result['status']!='needs_confirmation':raise RuntimeError('历史准备未完成：'+str(result))
    check_hashes(protected);bootstrap()
    frozen=load(result['snapshot']);check_hashes(frozen['files']);check_hashes(frozen['input_hashes'])
    from arrival_core.colored_operations import execution as original_execution
    plan=load(output/'technical/operations-input-candidate.json')['plan']
    preview=[]
    for row in plan['details']:
        v=row['values'];calc=original_execution({'authority':{'quantity':v['业务确认数量'],'amount':v['业务确认金额JPY']},
                   'packaging':{'declaration_factor':v['申报换算系数']}})
        preview.append({'row_id':v['稳定行号'],'source_row':row['source_rows']['business'],
          'carton':v['箱号'],'code':v['商品编码'],'declaration_quantity':v['申报数量'],
          'business_amount':v['业务确认金额JPY'],'price':calc['price'],'amount':str(calc['amount']),
          'rounded':calc['rounded'],'adjusted':calc['adjusted'],'confirmed':False})
    save(root/'unconfirmed-math-preview.json',preview)
    boundary={str(root/'unconfirmed-math-preview.json'):digest(root/'unconfirmed-math-preview.json'),
              str(output/'result.json'):digest(output/'result.json'),**frozen['files']}
    save(root/'before-scoring-boundary.json',{'files':boundary,'answers_consumed':False,
       'historical_preexposed_sample':True,'independent_new_batch_verified':False})
    # First parsing of historical answer cells; earlier reads only pinned its SHA.
    from arrival_core import _p0_frozen as p0
    answer=Path(config['answer_customs']).resolve();book=p0.Book(answer.read_bytes(),str(answer))
    sheet=next(s for s in book.sheets if s.name=='图片处理');answers=defaultdict(list)
    for ri in sorted(sheet.rows):
        if ri<2:continue
        code=p0.text(sheet.v(ri,'B'));qty=p0.numeric_text(sheet.v(ri,'F'))
        if not code or qty is None:continue
        answers[(p0.text(sheet.v(ri,'A')),code)].append({'row':ri,'quantity':str(qty),
          'price':p0.text(sheet.v(ri,'G')),'amount':p0.text(sheet.v(ri,'P'))})
    differences=[];unmatched=[];amount_delta=Fraction();matched=0;answer_positions=[]
    for row in preview:
        candidates=answers[(row['carton'],row['code'])]
        if len(candidates)!=1:unmatched.append(row['row_id']);continue
        expected=candidates.pop();matched+=1;answer_positions.append(expected['row'])
        actual_amount=Fraction(row['amount']);expected_amount=Fraction(expected['amount'])
        if row['price']!=Fraction(expected['price']) or actual_amount!=expected_amount or Fraction(row['declaration_quantity'])!=Fraction(expected['quantity']):
            differences.append({'row_id':row['row_id'],'source_row':row['source_row'],'answer_row':expected['row'],
              'computed_price':row['price'],'historical_price':expected['price'],
              'computed_amount':row['amount'],'historical_amount':expected['amount'],
              'computed_minus_historical_amount':str(actual_amount-expected_amount),'applied':False})
        amount_delta+=actual_amount-expected_amount
    score={'scope':'unconfirmed_operations_context_math_after_preparation_not_a_generated_pair',
      'preview_rows':len(preview),'matched_answer_rows':matched,'unmatched_preview_rows':unmatched,
      'unmatched_answer_rows':sum(map(len,answers.values())),
      'answer_order_preserved':answer_positions==sorted(answer_positions),
      'different_price_or_amount_rows':len(differences),'computed_minus_historical_amount_jpy':str(amount_delta),
      'differences':differences,'automatic_tail_adjustments':0,'tax_verified':False,
      'pair_generated':False,'formal_output':False,'answers_applied_to_input':False}
    save(root/'post-run-answer-score.json',score)
    check_hashes(protected);check_hashes(boundary);bootstrap()
    groups=load(output/'technical/conversion-groups.json')
    unresolved=set(r['row_id'] for g in groups for r in g['rows'] if not r['raw_link_exists'])
    summary={'scope':'historical_replay_P3C_phase1','status':result['status'],'facts':result['facts'],
      'special_groups':len(groups),'unmatched_special_operations_rows':len(unresolved),
      'groups_with_unmatched_source_rows':sum(bool(g['unmatched_raw_scope_rows']) for g in groups),
      'post_run_score':score,'can_enter_pair_calculation':False,'business_exception_total':None,
      'business_files':[],'actual_human_actions':None,'time_saved_seconds':None,
      'protected_files_checked':len(protected),'changed_files':[],
      'new_independent_batch_verified':False,'workbuddy_used':False,'websites_accessed':False,
      'd1_accessed':False,'formal_output':False}
    save(root/'acceptance.json',summary)
    note='# P3-C 第一阶段 KMT1002 历史回放验收\n\n'
    note+='结果：已从原始附件生成初步整理、资料库候选、运营输入候选和来源绑定的换算分组；停在待确认，不能进入双表计算。\n\n'
    f=result['facts']
    note+=f'- 原件{f["raw_rows"]}行；原始零售Subtotal {f["raw_retail_subtotal_jpy"]} JPY。第3＋4步上下文{f["operations_rows"]}行，业务来源金额 {f["business_source_amount_jpy"]} JPY。两类金额分开保存，不替换。\n'
    note+=f'- 箱号＋编码唯一对应{f["exact_source_links"]}行；原件未配对{f["unmatched_raw_rows"]}行、后续表未配对{f["unmatched_operations_rows"]}行。已配对来源的实质名称/数量差异{f["current_source_conflict_rows"]}条；另有{f["source_formatting_difference_rows"]}处仅末尾空白差异留作格式证据，不重复要求人工确认。前述局部计数不代表全批0异常，也不批准身份。\n'
    note+=f'- {f["special_conversion_rows"]}行特殊换算归为{len(groups)}组；按申报/业务数量比、内部数量/盒数和源文件/列关系分组，逐行保留证据。{len(unresolved)}个特殊换算行还没有原件精确对应，分组确认不能消除这些异常。\n'
    note+='- 未自动确认实际单位、业务金额基准、换算范围或商品身份；已有运营名称、材质、F/备注/YD完整保存在候选中，资料库不覆盖，不要求补长期版本或历史库资料。\n'
    note+=f'- 运行完成并锁定输入/候选/预览哈希后才读取历史最终答案。原rc.5数学助手的未确认预览有{len(differences)}行差异，计算金额比历史多{amount_delta} JPY；差异单列于post-run-answer-score.json，未自动调平。未生成工作簿双表，税金/双表格式与正式放行均未验证。\n'
    note+='\n真实待确认事项：本批第3步业务基准及实际单位；按组核对来源换算范围；解决未配对及当前来源差异。没有要求372行逐行重复填，实际真人输入/确认次数及工时未测量。\n'
    note+=f'\n原件、原库、现有引擎和既有证据共{len(protected)}项保护哈希前后一致；复用依赖锁通过，D1未访问，正式门禁关闭。此为已参与开发的历史回放；独立新批次仍未验证，WorkBuddy未安装或测试，五站未访问。\n'
    (root/'P3C_PHASE1_ACCEPTANCE_20261103.md').write_text(note,encoding='utf-8')
    return summary


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--config',required=True);args=parser.parse_args()
    result=validate(load(args.config));print(__import__('json').dumps({k:v for k,v in result.items() if k in ('status','facts','special_groups','unmatched_special_operations_rows','protected_files_checked')},ensure_ascii=False))
