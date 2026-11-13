"""Reproducible local-only validation; all private paths arrive via a config."""
import argparse
import csv
import json
from collections import Counter
from pathlib import Path

from product_reference.database import inspect, clone, digest, import_bundle
from product_reference.query import BatchQuery, comparable, evidence, has_material
from product_reference.workbooks import extract, collect_bundle
from product_reference.b4_store import verify_bundle
from source_adapters.common import write_bundle
from source_adapters.order import collect


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def save(path, value):
    with Path(path).open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)


def query_rows(records):
    return [{'row_id': r['source_record_id'], **r['identity'], 'source': r['provenance']} for r in records]


def metrics(result, expected):
    counts = Counter(result['summary'])
    for r, original in zip(result['rows'], expected, strict=True):
        candidates = r['candidates']
        counts['candidate_rows'] += bool(candidates)
        counts['exact_identity_candidate_rows'] += any(c['match']=='exact_observed_identity' for c in candidates)
        counts['material_reference_rows'] += any(has_material(c) for c in candidates)
        counts['conflict_rows'] += any(c['conflicts'] for c in candidates)
        values = {comparable(c['fields']['internal_name']['value']) for c in candidates if 'internal_name' in c['fields']}
        expected_name = original['fields'].get('internal_name',{}).get('value')
        if expected_name:
            counts['name_comparison_denominator'] += bool(values)
            counts['name_agrees_with_any_candidate'] += comparable(expected_name) in values
            contains = any(min(len(comparable(expected_name)),len(v))>=4 and
                           (comparable(expected_name) in v or v in comparable(expected_name)) for v in values)
            counts['name_text_containment_not_identity_precision'] += contains
            if len(candidates)==1 and values:
                counts['single_candidate_name_denominator'] += 1
                counts['single_candidate_name_agrees'] += comparable(expected_name) in values
                counts['single_candidate_name_text_containment'] += contains
        counts['query_rows'] += 1
    return dict(counts)


def main():
    p=argparse.ArgumentParser();p.add_argument('--config',required=True);args=p.parse_args()
    cfg=load(args.config);out=Path(cfg['output']).resolve();out.mkdir(parents=True,exist_ok=False)
    database=Path(cfg['database']).resolve(strict=True)
    before=digest(database);print('audit',flush=True)
    audit=inspect(database);save(out/'database-audit.json',audit)
    protected={str(Path(p).resolve()):digest(p) for p in cfg.get('protected_files',[])}
    training=cfg['training'];holdout=cfg['holdout'];auth=cfg['authorization']
    training_mapping=load(training['mapping']);holdout_mapping=load(holdout['mapping'])
    source_hashes={str(Path(spec['file']).resolve()):digest(spec['file']) for spec in (training,holdout)}
    assert source_hashes[str(Path(training['file']).resolve())] != source_hashes[str(Path(holdout['file']).resolve())]
    records=extract(training['file'],training_mapping,source_id=training['source_id'],source_version='sha256:'+digest(training['file']),authorization_reference=auth['reference'])
    expected=extract(holdout['file'],holdout_mapping,source_id='heldout-query-only',source_version='sha256:'+digest(holdout['file']),authorization_reference=auth['reference'])
    holdout_queries=query_rows(expected);heldout_hash=digest(holdout['file'])
    print('query original B4 snapshot',flush=True)
    baseline=BatchQuery(database).run(holdout_queries,exclude_file_sha256=[heldout_hash]);save(out/'holdout-before-import.json',baseline)
    work=out/'runtime'/'working.sqlite3';print('clone',flush=True);snapshot=clone(database,work);save(out/'working-copy.json',snapshot)
    # Replay existing bundles without reinitialization. All existing auth is scoped.
    replay=[]
    for spec in cfg.get('reimport_bundles',[]):
        result=import_bundle(work,spec['bundle'],load(spec['authorization']),purchase_policy=load(spec['purchase_policy']) if spec.get('purchase_policy') else None)
        assert result['status']=='unchanged_duplicate';replay.append(result)
    save(out/'existing-bundle-replay.json',replay)
    if cfg.get('opening_request'):
        print('recollect real source Excel',flush=True)
        request=load(cfg['opening_request']);source=Path(request['files'][0]['path'])
        source_hashes[str(source.resolve())]=digest(source)
        manifest=write_bundle(request,list(collect(request)),out/'recollected-opening','order')
        result=import_bundle(work,out/'recollected-opening',load(cfg['reimport_bundles'][0]['authorization']))
        save(out/'recollected-opening-result.json',{'manifest':manifest,'result':result})
        assert result['statistics']['observations']==audit['tables']['source_ingest_observations']['rows']
    print('collect and import historical training batch',flush=True)
    collect_bundle(training['file'],training_mapping,out/'training-bundle',source_id=training['source_id'],
                   source_version='sha256:'+digest(training['file']),authorization_reference=auth['reference'])
    checked=verify_bundle(out/'training-bundle')
    assert len(checked['records'])==len(records)
    imported=import_bundle(work,out/'training-bundle',auth);save(out/'training-import.json',imported)
    repeat=import_bundle(work,out/'training-bundle',auth);assert repeat['status']=='unchanged_duplicate'
    save(out/'training-repeat.json',repeat)
    print('separate same-batch replay from held-out batch',flush=True)
    replay_result=BatchQuery(work).run(query_rows(records));save(out/'same-batch-diagnostic-only.json',replay_result)
    heldout=BatchQuery(work).run(holdout_queries,exclude_file_sha256=[heldout_hash]);save(out/'holdout-after-import.json',heldout)
    assert not any(s['file_sha256']==heldout_hash for r in heldout['rows'] for c in r['candidates'] for s in c['sources'])
    # Resolve a real persisted evidence blob, rather than trusting only JSON pointers.
    checked_evidence=0
    for r in heldout['rows']:
        if checked_evidence>=20:break
        for candidate in r['candidates'][:1]:
            for material in candidate['material_references'][:1]:
                evidence(work,material['source']['observation_sha256'],material['evidence'][0]['file']);checked_evidence+=1
    with (out/'missing-data.csv').open('x',encoding='utf-8-sig',newline='') as stream:
        writer=csv.writer(stream);writer.writerow(['row_id','source_sheet','source_row','code','status','missing_identity','candidate_count','conflict_fields','source_value_issues','material_reference_available'])
        for row in heldout['rows']:
            source=row['query'].get('source',{});candidates=row['candidates']
            writer.writerow([row['row_id'],source.get('sheet'),source.get('row'),row['query'].get('code_raw'),row['status'],
                ';'.join(row['missing_identity']),len(candidates),';'.join(sorted({k for c in candidates for k in c['conflicts']})),
                ';'.join(sorted({i['field'] for c in candidates for i in c['source_issues']})),any(has_material(c) for c in candidates)])
    final_audit=inspect(work);save(out/'working-database-audit.json',final_audit)
    assert digest(database)==before
    assert all(digest(path)==expected for path,expected in protected.items())
    assert all(digest(path)==expected for path,expected in source_hashes.items())
    summary={'base_commit':cfg['base_commit'],'status':'passed','original_database_unchanged':True,'original_database_sha256':before,
        'existing_observations':audit['tables']['source_ingest_observations']['rows'],
        'new_training_rows':len(records),'holdout_rows':len(expected),'source_files_unchanged':True,
        'existing_bundles_reimported_without_duplicate_observations':bool(replay),'evidence_blobs_verified':checked_evidence,
        'original_b4_holdout_retrieval':metrics(baseline,expected),'cross_batch_after_training':metrics(heldout,expected),
        'same_batch_diagnostic_not_coverage':metrics(replay_result,records),
        'new_batch_future_coverage':'not_established_retrospective_holdout_only',
        'independently_adjudicated_match_precision':None,'name_agreement_is_not_approval':True,
        'frozen_files_checked':len(protected),'d1_accessed':False,'formal_output':False,'workbuddy_tested':False}
    save(out/'acceptance.json',summary);print(json.dumps(summary,ensure_ascii=False),flush=True)


if __name__=='__main__':main()
