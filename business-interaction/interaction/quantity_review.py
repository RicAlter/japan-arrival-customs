"""Independent JAN purchase/receipt observations; never an Excel or A03 writer."""
from collections import Counter, defaultdict
from fractions import Fraction
from pathlib import Path
from decimal import Decimal, InvalidOperation
from copy import deepcopy
from datetime import date
import shutil
import re

from . import load, save, digest, key, Rejected
from .preparation_sources import Index, code, workbook_records


def number(value):
    if isinstance(value, bool) or value in (None, ''):return None
    try:
        d=Decimal(str(value))
        return Fraction(d) if d.is_finite() and d>=0 else None
    except (ValueError, InvalidOperation):return None


def text(value):return None if value is None else str(value)


def proven(item):
    return isinstance(item,dict) and item.get('confirmed') is True and bool(item.get('reference'))


def unit(record,kind,policy):
    # A mapped unit column is source evidence. Product specification is not a
    # purchase unit and is never parsed into a multiplier/default unit here.
    if record.get('unit'):return str(record['unit']).strip()
    matches=[b for b in policy.get('unit_bindings',[]) if proven(b) and b.get('kind')==kind and code(b.get('jan'))==record['jan']]
    values={b.get('unit') for b in matches if b.get('unit')}
    return next(iter(values)) if len(values)==1 else None


def factor(record,kind,target_jan,target_unit,policy):
    original_unit=unit(record,kind,policy)
    if record['jan']==target_jan and original_unit and original_unit==target_unit:return Fraction(1)
    factors={number(b.get('factor')) for b in policy.get('conversions',[]) if proven(b)
             and code(b.get('from_jan'))==record['jan'] and code(b.get('to_jan'))==target_jan
             and b.get('from_unit')==original_unit and b.get('to_unit')==target_unit
             and original_unit and target_unit}
    factors.discard(None);factors.discard(Fraction(0))
    return next(iter(factors)) if len(factors)==1 else None


def purchase_lines(records,accepted,as_of=None):
    """Deduplicate repeated exports, retaining ambiguous/versioned order lines."""
    groups=defaultdict(list);excluded=[];ineffective=set()
    for raw in records:
        r=deepcopy(raw);r['jan']=code(r.get('jan') or r.get('sku'))
        k=(str(r.get('order_id') or ''),r['jan'],str(r.get('order_line_id') or ''),str(r.get('spec') or ''),str(r.get('yd') or ''))
        if r.get('status') not in accepted:
            ineffective.add(k);excluded.append({**r,'excluded_reason':'purchase_status_not_effective'});continue
        if as_of:
            try:order_date=date.fromisoformat(str(r.get('order_date') or '')[:10].replace('/','-'))
            except ValueError:
                r['date_unresolved']=True
            else:
                if order_date>date.fromisoformat(as_of):
                    excluded.append({**r,'excluded_reason':'purchase_after_batch_cutoff'});continue
        groups[k].append(r)
    valid=[];ambiguous=[];duplicates=0
    for identity,items in groups.items():
        positions={key(r.get('source',{})):r for r in items};items=list(positions.values())
        payloads={key({k:text(number(r.get(k))) if k in {'quantity','cut_quantity'} else text(r.get(k))
                       for k in ['quantity','unit','status','cut_quantity','cancelled','order_date']}) for r in items}
        per_export=Counter((r.get('source',{}).get('sha256'),r.get('source',{}).get('sheet')) for r in items)
        reason=None
        if not identity[0] or not identity[1]:reason='purchase_order_or_code_missing'
        elif identity in ineffective:reason='purchase_order_status_conflict'
        elif items[0].get('date_unresolved'):reason='purchase_date_unresolved'
        elif len(payloads)>1:reason='purchase_order_line_version_conflict'
        elif not identity[2] and any(n>1 for n in per_export.values()):reason='purchase_order_line_identity_ambiguous'
        elif number(items[0].get('quantity')) is None:reason='purchase_quantity_invalid'
        elif items[0].get('cut_quantity') not in (None,'',0,'0',0.0,'0.0') or items[0].get('cancelled') in ('是',True):
            reason='purchase_cancellation_quantity_basis_unresolved'
        if reason:
            ambiguous.extend({**r,'excluded_reason':reason} for r in items);continue
        duplicates+=len(items)-1
        valid.append({**items[0],'all_sources':[r.get('source',{}) for r in items]})
    return valid,excluded,ambiguous,duplicates


def related(jan,index):
    hit=index.lookup(jan);aliases={jan};pcs=set()
    for r in hit['records']+hit['related']:
        for field in ['jan','sku']:
            if r.get(field):aliases.add(code(r[field]))
    for r in hit['links']:
        main,piece=code(r.get('jan')),code(r.get('pcs'))
        if jan in (main,piece):
            aliases.update(x for x in (main,piece) if x);pcs.update(x for x in (main,piece) if x and x!=jan)
    return aliases,pcs,hit['status']=='box_code_conflict'


def reconcile(arrivals,purchases,history,index,policy,batch_id):
    valid,excluded,ambiguous,duplicates=purchase_lines(purchases,set(policy.get('accepted_purchase_statuses',['已采购'])),policy.get('as_of'))
    grouped=defaultdict(list)
    for r in arrivals:grouped[r['jan']].append(r)
    all_history=[];seen={};history_rejected=[]
    for r in history:
        source=r.get('source',{});pos=(source.get('sha256'),source.get('sheet'),source.get('row'))
        if r.get('batch_id')==batch_id:
            history_rejected.append({**r,'excluded_reason':'current_batch_not_historical'});continue
        if pos in seen:
            if seen[pos]!=r.get('batch_id'):history_rejected.append({**r,'excluded_reason':'same_source_assigned_multiple_batches'})
            continue
        seen[pos]=r.get('batch_id');all_history.append(r)
    results={}
    purchase_by_code=defaultdict(list);bad_by_code=defaultdict(list);history_by_code=defaultdict(list)
    for r in valid:purchase_by_code[r['jan']].append(r)
    for r in ambiguous:bad_by_code[r['jan']].append(r)
    for r in all_history:history_by_code[r['jan']].append(r)
    # A box order referenced by two distinct arrival JANs is one observation,
    # not two independently spendable purchase balances. Keep it unallocated.
    shared=defaultdict(set)
    for jan in grouped:
        aliases,_,conflict=related(jan,index)
        if conflict:aliases={jan}
        for alias in aliases:
            for r in purchase_by_code[alias]:shared[key(r.get('source',{}))].add(jan)
    for jan,items in grouped.items():
        aliases,pcs,link_conflict=related(jan,index)
        if link_conflict:aliases={jan}
        candidates=[r for c in sorted(aliases) for r in purchase_by_code[c]]
        bad=[r for c in sorted(aliases) for r in bad_by_code[c]]
        previous=[r for c in sorted(aliases) for r in history_by_code[c]]
        reasons=[]
        is_jan=bool(re.fullmatch(r'\d{8,14}',jan))
        if policy.get('require_jan_syntax') and not is_jan:reasons.append('nonstandard_code_not_verified_JAN')
        if link_conflict:reasons.append('main_pcs_link_conflict')
        if not candidates:reasons.append('effective_purchase_order_source_insufficient')
        if bad:reasons.extend(sorted({r['excluded_reason'] for r in bad}))
        if any(len(shared[key(r.get('source',{}))])>1 for r in candidates):
            reasons.append('shared_order_quantity_across_JAN_groups_not_allocated')
        purchase_scope=policy.get('purchase_coverage',{})
        history_scope=policy.get('history_coverage',{})
        if not(purchase_scope.get('complete') is True and purchase_scope.get('reference')):reasons.append('purchase_order_scope_incomplete')
        if not(history_scope.get('complete') is True and history_scope.get('reference')):reasons.append('historical_arrival_scope_incomplete')
        if history_rejected:reasons.append('historical_source_scope_rejected')
        selected=policy.get('order_scopes',{}).get(jan)
        if selected is not None:
            if not proven(selected):reasons.append('purchase_order_binding_unconfirmed')
            else:
                order_ids=set(selected.get('order_ids',[]))
                candidates=[r for r in candidates if r['order_id'] in order_ids]
                if not candidates:reasons.append('bound_order_not_found')
                if any(not r.get('order_id') or r['order_id'] not in order_ids for r in previous):
                    reasons.append('historical_order_binding_insufficient')
        elif len({r.get('yd') for r in candidates if r.get('yd')})>1:
            reasons.append('same_jan_product_version_or_YD_conflict')
        arrival_quantities=[number(r.get('quantity')) for r in items]
        if None in arrival_quantities:reasons.append('arrival_quantity_invalid')
        units={unit(r,'arrival',policy) for r in items}
        target_unit=next(iter(units)) if len(units)==1 and None not in units else None
        target=policy.get('comparison_units',{}).get(jan)
        if proven(target) and target.get('unit'):target_unit=target['unit']
        if target_unit is None:reasons.append('arrival_quantity_unit_unconfirmed')
        totals={}
        for kind,records in [('arrival',items),('purchase',candidates),('history',previous)]:
            converted=[]
            for r in records:
                f=factor(r,kind,jan,target_unit,policy);q=number(r.get('quantity'))
                if f is None or q is None:reasons.append(kind+'_unit_or_confirmed_conversion_missing')
                else:converted.append(q*f)
            totals[kind]=sum(converted,Fraction(0)) if len(converted)==len(records) else None
        # Missing prior records cannot mean zero unless the history scope is
        # explicitly complete, including an explicitly documented first receipt.
        reasons=sorted(set(reasons))
        complete=not reasons and bool(candidates)
        remaining=totals['purchase']-totals['history']-totals['arrival'] if complete else None
        status='source_insufficient'
        if complete:status='pending_future_arrival' if remaining>0 else 'over_received' if remaining<0 else 'fully_received'
        raw_purchase=[number(r['quantity']) for r in candidates]
        raw_history=[number(r.get('quantity')) for r in previous]
        result={'jan':jan,'identifier_is_standard_jan':is_jan,'arrival_rows':[r.get('row') for r in items],'aliases':sorted(aliases),'pcs_codes':sorted(pcs),
            'purchase_order_ids':sorted({r['order_id'] for r in candidates}),'purchase_order_lines':candidates,'purchase_ambiguous_lines':bad,
            'historical_observations':previous,'current_arrival_observations':items,
            'current_arrival_raw':text(sum(arrival_quantities,Fraction(0))) if None not in arrival_quantities else None,
            'purchase_raw_sum_unconverted':text(sum(raw_purchase,Fraction(0))) if candidates and None not in raw_purchase else None,
            'historical_raw_sum_observed_only':text(sum(raw_history,Fraction(0))) if previous and None not in raw_history else None,
            'raw_sums_do_not_establish_unit_or_complete_scope':True,
            'comparison_unit':target_unit,'purchase_total':text(totals['purchase']) if complete else None,
            'historical_received':text(totals['history']) if complete else None,'current_received':text(totals['arrival']) if complete else None,
            'remaining_pending':text(max(remaining,Fraction(0))) if complete else None,
            'cumulative_difference':text(-remaining) if complete else None,'status':status,'reasons':reasons,
            'is_error':status=='over_received','followup_next_batch':status=='pending_future_arrival',
            'arrival_quantity_substituted_for_purchase':False,'business_confirmed':False}
        results[jan]=result
    counts=Counter(r['status'] for r in results.values());n_comparable=sum(r['status']!='source_insufficient' for r in results.values())
    summary={'arrival_rows':len(arrivals),'jan_groups':len(results),'order_matched_jans':sum(bool(r['purchase_order_lines']) for r in results.values()),
        'standard_jan_groups':sum(r['identifier_is_standard_jan'] for r in results.values()),
        'nonstandard_code_groups':sum(not r['identifier_is_standard_jan'] for r in results.values()),
        'direct_order_matched_jans':sum(any(p['jan']==j for p in r['purchase_order_lines']) for j,r in results.items()),
        'linked_only_order_matched_jans':sum(bool(r['purchase_order_lines']) and all(p['jan']!=j for p in r['purchase_order_lines']) for j,r in results.items()),
        'pcs_only_order_matched_jans':sum(bool(r['purchase_order_lines']) and all(p['jan']!=j for p in r['purchase_order_lines']) and any(p['jan'] in r['pcs_codes'] for p in r['purchase_order_lines']) for j,r in results.items()),
        'sku_alias_only_order_matched_jans':sum(bool(r['purchase_order_lines']) and all(p['jan']!=j and p['jan'] not in r['pcs_codes'] for p in r['purchase_order_lines']) for j,r in results.items()),
        'history_observed_jans':sum(bool(r['historical_observations']) for r in results.values()),'comparable_jans':n_comparable,
        'status_counts':dict(counts),'over_received_jans':counts['over_received'] if n_comparable else None,
        'pending_future_arrival_jans':counts['pending_future_arrival'] if n_comparable else None,
        'source_insufficient_jans':counts['source_insufficient'],'reason_counts':dict(Counter(reason for r in results.values() for reason in r['reasons'])),
        'deduplicated_purchase_export_observations':duplicates,'excluded_purchase_lines':len(excluded),'ambiguous_purchase_lines':len(ambiguous),
        'excluded_purchase_reason_counts':dict(Counter(r['excluded_reason'] for r in excluded)),
        'excluded_history_observations':len(history_rejected),'workbook_modified':False,'confirmed':0}
    return {'schema':'jan-quantity-review/1','batch_id':batch_id,'rows':results,'summary':summary,
        'excluded_purchase_lines':excluded,'excluded_history_observations':history_rejected,
        'frontend':{'needs_attention':{'over_received_jans':summary['over_received_jans'],'source_insufficient_jans':counts['source_insufficient'],
                                     'reason_counts':summary['reason_counts']},
                    'future_arrival_jans':summary['pending_future_arrival_jans'],
                    'future_arrivals_scope':'undetermined_due_to_sources' if not n_comparable else 'comparable_records_only',
                    'future_arrivals':[{k:r[k] for k in ['jan','purchase_total','historical_received','current_received','remaining_pending','comparison_unit']}
                                       for r in results.values() if r['followup_next_batch']]}}


def capture(configs,folder,kind,current_sha):
    records=[];assets=[];seen=set()
    for config in configs:
        original=Path(config['path']).resolve(strict=True);sha=digest(original)
        if config.get('sha256') and config['sha256']!=sha:raise Rejected('数量来源摘要变化：'+str(original))
        if kind=='history' and sha==current_sha:raise Rejected('本批原件不能当历史已到重复计入')
        frozen=folder/(sha[:12]+'-'+original.name)
        if frozen.exists() and digest(frozen)!=sha:raise Rejected('固定数量来源被改动')
        if not frozen.exists():shutil.copyfile(original,frozen)
        if digest(frozen)!=sha or digest(original)!=sha:raise Rejected('数量来源捕获期间变化')
        identity=(sha,config['sheet'],config.get('batch_id') if kind=='history' else None)
        if identity in seen:continue
        seen.add(identity);captured={**config,'path':str(frozen),'sha256':sha,'kind':'quantity_'+kind}
        for r in workbook_records(captured):
            r['jan']=code(r.get('jan') or r.get('sku'));r['batch_id']=config.get('batch_id')
            if kind=='history' and not r['batch_id']:raise Rejected('历史到货来源须明确独立批次标识')
            records.append(r)
        assets.append({**captured,'original':str(original)})
    return records,assets


def build_quantity_review(source,records,settings,back,batch_id):
    if not isinstance(settings,dict):raise Rejected('quantity_review须为配置对象')
    folder=Path(back)/'fixed-inputs/quantity';folder.mkdir(parents=True,exist_ok=True)
    source_sha=digest(source['path'])
    purchases,passets=capture(settings.get('purchase_sources',[]),folder,'purchase',source_sha)
    history,hassets=capture(settings.get('history_sources',[]),folder,'history',source_sha)
    arrivals=[{'jan':r['code'],'quantity':r['source']['cells']['qty']['value'],'row':i,'source_row':r['source_row'],
               'batch_id':batch_id,'source':{'path':source['path'],'sha256':source_sha,'sheet':source['sheet'].name,'row':r['source_row'],
                                           'cell':r['source']['cells']['qty']['cell']}}
              for i,r in enumerate(source['rows'],2)]
    result=reconcile(arrivals,purchases,history,Index(records),{**settings,'require_jan_syntax':True},batch_id)
    result['source_sha256']=source_sha;result['sources']={'purchase':passets,'history':hassets}
    result['database_fields_are_reference_only_not_purchase_transactions']=True
    result['implementation_sha256']=digest(Path(__file__))
    result['policy']={k:v for k,v in settings.items() if k not in {'purchase_sources','history_sources'}}
    file=Path(back)/'jan-quantity-review.json';save(file,result)
    return {'path':str(file),'sha256':digest(file),'code_sha256':result['implementation_sha256'],'summary':result['summary'],'frontend':result['frontend']}


def refresh_quantity_review(config,settings):
    from native_copy.profiles import inspect_source
    back=Path(config['background'])
    if digest(config['source'])!=config['source_sha256']:raise Rejected('原始到货固定快照变化')
    prior=config.get('quantity_review')
    if prior:
        if digest(prior['path'])!=prior['sha256']:raise Rejected('原数量核对证据摘要变化')
        archive=back/('jan-quantity-review-'+prior['sha256']+'.json')
        if not archive.exists():shutil.copyfile(prior['path'],archive)
    context={}
    for row in load(back/'evidence.json')['rows'].values():
        for record in row.get('sources',[])+row.get('code_links',[])+row.get('related_procurement',[]):
            identity=key({k:record.get(k) for k in ['jan','sku','pcs','source']})
            context[identity]=record
    return build_quantity_review(inspect_source(config['source']),list(context.values()),settings,back,config['batch_label'])
