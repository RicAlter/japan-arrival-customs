"""Explicit authorized input list; no answer reading, scanning, confirmation or math."""
import argparse
import json
from pathlib import Path
from native_copy.service import execute, registered_copy
from native_copy.support import bootstrap, check_hashes, digest, load, save


def validate(config):
    bootstrap()
    report = Path(config['report']).resolve()
    if report.exists():
        raise ValueError('验收报告目录已存在，拒绝覆盖')
    report.mkdir(parents=True)
    protected = config['protected_files']
    check_hashes(protected)
    save(report / 'protected-before.json', {p: digest(p) for p in protected})
    cases = []
    for case in config['cases']:
        request = case['request']
        source_before = digest(request['input_file'])
        result = execute(case['output'], request)
        checked = None
        if result['status'] == 'prepared_reference_copy':
            registered = registered_copy(case['output'])
            checked = {'export_id': registered['export_id'], 'a_version': registered['a_version'],
                       'copy_sha256': registered['copy_sha256'], 'confirmed': registered['confirmed_fields']}
        case_result = {'label': case['label'], 'evidence_type': 'authorized_historical_or_provided_layout',
                       'independent_new_batch': False, 'source_before': source_before,
                       'source_after': digest(request['input_file']), 'result': result,
                       'registration_checked': checked}
        save(report / (str(len(cases) + 1) + '-case.json'), case_result)
        cases.append(case_result)
    check_hashes(protected); lock = bootstrap()
    summary = {'schema': 'a01-history-validation/1', 'cases': cases,
               'prepared_copies': sum(c['result']['status'] == 'prepared_reference_copy' for c in cases),
               'protected_files': len(protected), 'protected_unchanged': True,
               'reused_dependencies': len(lock['files']), 'formal_output': False,
               'human_return_implemented': False, 'human_approval_observed': False,
               'split_merge_implemented': False, 'b_calculation_run': False, 'pair_output_run': False,
               'independent_new_batch_verified': False, 'workbuddy_verified': False}
    save(report / 'acceptance.json', summary)
    return summary


if __name__ == '__main__':
    p = argparse.ArgumentParser(); p.add_argument('--config', required=True); args = p.parse_args()
    value = validate(load(args.config))
    print(json.dumps({k: v for k, v in value.items() if k != 'cases'}, ensure_ascii=False))
    raise SystemExit(0 if value['prepared_copies'] == len(value['cases']) else 2)
