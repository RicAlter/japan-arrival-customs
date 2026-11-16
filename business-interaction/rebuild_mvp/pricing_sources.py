"""Coordinate checked pricing/rate references; historical rates are not law."""
from pathlib import Path
import re
from .service import MvpError,digest,load_json
from .storage import identity
from .quantity_sources import Evidence,norm
from .quantity_conversion import read_quantity_source
from .quantity_export import edits,compare
from .quantity_math import number,UNITS
from .pricing_math import rate
from .xlsxio import read_book


def quantity_delivery(reference):
    contract=read_quantity_source(reference)
    task=Path(reference['path']).resolve().parent
    job=load_json(task/'job.json')
    if (job.get('mode')!='quantity_conversion' or job.get('quantity_source')!=reference or
            job['upstream']!=contract['upstream'] or job['code']['sha256']!=contract['code_sha256'] or
            job.get('step')!='exported' or len(job.get('business_files',[]))!=1):
        raise MvpError('SOURCE_CHANGED','数量交付与契约不一致')
    path=Path(job['business_files'][0]).resolve(strict=True)
    expected=next((x['sha256']for x in job['artifacts']if Path(x['path']).resolve()==path),None)
    if not expected or digest(path)!=expected:
        raise MvpError('SOURCE_CHANGED','数量Excel交付发生变化')
    compare(contract['upstream']['path'],path,contract['upstream']['sheet'],edits(contract['rows']))
    binding={'path':str(path),'sha256':expected,'job_path':str(task/'job.json'),
             'job_sha256':digest(task/'job.json'),'quantity_source':reference}
    return contract,binding


class PricingEvidence(Evidence):
    def __init__(self,path):
        super().__init__(path,schema='arrival-price-tax-evidence/1',extra_roles={'tax_reference'})
        if sum(s['role']=='business_summary'for s in self.sources.values())>1:
            raise MvpError('CONFIG_INVALID','价格主表只能绑定一个已确认版本')
        self.formula_books={}
        self.index={}
        for item in self.data.get('rows',[]):
            self.index.setdefault((item.get('sheet'),item.get('row')),[]).append(item)

    def identity_refs(self,spec,scope,values):
        refs=self.refs(spec['identity_evidence'])
        for ref in refs:
            field=ref.get('field')
            if field not in {'code','name','ja','specification','yd'}or not norm(scope.get(field,''))or norm(ref['value'])!=norm(scope[field]):
                raise MvpError('INPUT_INVALID','价格来源商品身份原格与本行不符')
        for value in values:
            matching=[r for r in refs if r['source_id']==value['source_id']and r['sheet']==value['sheet']and r['row']==value['row']]
            if not any(r['field']in {'code','name','ja'}for r in matching):
                raise MvpError('INPUT_INVALID','每个价格原记录须有商品身份坐标')
        return refs

    def invoice_facts(self,spec,invoice,scope):
        if spec.get('basis')!='preserved_japanese_original':
            raise MvpError('INPUT_INVALID','须明确原始日方字段语义，不能采用旧计算价')
        fields={};proof={};issues=[]
        for field in ['quantity','price','amount']:
            try:
                refs=self.refs(spec[field])
                self.identity_refs(spec,scope,refs)
                if not all(r['role']in {'japanese_batch','reviewed_basics'}for r in refs):
                    raise MvpError('SOURCE_FORBIDDEN','原价金额不能取采购报价或已计算完成表')
                n=number(invoice[field])
                fields[field]=n is not None and any(number(r['value'])==n for r in refs)
                proof[field]=refs
                if not fields[field]:issues.append({'code':'ORIGINAL_SOURCE_VALUE_MISMATCH','field':field})
            except (MvpError,KeyError,TypeError)as exc:
                fields[field]=False;issues.append({'code':getattr(exc,'code','INPUT_INVALID'),'field':field,'message':str(exc)})
        currency_refs=self.refs(spec['currency_evidence'])
        prices=proof.get('price',[])
        if (spec.get('currency')!='JPY' or not all(r['role']in {'japanese_batch','reviewed_basics'}for r in currency_refs)
                or not any(re.search(r'JPY|日元|円',r['value'])and not re.search(r'CNY|人民币|USD|美元',r['value'])
                           and any(r['source_id']==p['source_id']and (r['row']==p['row']or(r['column']==p['column']and r['row']<p['row']))for p in prices)for r in currency_refs)):
            raise MvpError('INPUT_INVALID','原始日元币种须取同记录或单价列明确表头')
        identities=self.identity_refs(spec,scope,[ref for values in proof.values()for ref in values])
        return {'source_fields':fields,'currency':'JPY','evidence':proof,'identity_evidence':identities,'currency_evidence':currency_refs},issues

    def rate_fact(self,fact):
        refs=self.refs(fact['evidence'])
        if not all(r['role']in {'tax_reference','japanese_batch','reviewed_basics'}for r in refs):
            raise MvpError('SOURCE_FORBIDDEN','该来源未许可提供税率')
        n=rate(fact['value'])
        if n is None:
            raise MvpError('INPUT_INVALID','税率不是明确数值')
        if fact.get('basis')=='formula_multiplier':
            verified=[]
            for ref in refs:
                source=self.sources[ref['source_id']]
                if source['path']not in self.formula_books:
                    self.formula_books[source['path']]=read_book(source['path'])
                book=self.formula_books[source['path']]
                sheet=next((x for x in book['sheets']if x['name']==ref['sheet']),None)
                row=next((r for r in sheet['rows']if r['row']==ref['row']),None)if sheet else None
                formula=row['formulas'].get(ref['column'])if row else None
                if not formula or formula!=fact.get('formula'):
                    raise MvpError('INPUT_INVALID','税率公式原文不符')
                # Only a final, explicit constant multiplier of the pinned formula.
                match=re.search(r'\*\s*(\d+(?:\.\d+)?%?)\s*$',formula)
                if not match or rate(match[1])!=n:
                    raise MvpError('INPUT_INVALID','税率不是该公式末尾明确常数乘数')
                verified.append({**ref,'formula':formula})
            refs=verified
        elif not any(rate(x['value'])==n for x in refs):
            raise MvpError('INPUT_INVALID','税率与数值原格不符')
        return {**fact,'evidence':refs,'scope':'provided_historical_reference_not_professional_approval'}

    def quote_fact(self,fact,display,scope):
        refs=self.refs(fact['evidence'])
        self.identity_refs(fact,scope,refs)
        allowed={'business_summary','purchase_list','order_detail','reviewed_basics'}
        if not all(r['role']in allowed for r in refs):
            raise MvpError('SOURCE_FORBIDDEN','官方售价或非采购来源不能作采购事实')
        quote_sources={r['source_id']for r in refs}
        if any(r['role']in {'purchase_list','order_detail'}for r in refs):
            if fact.get('record_state')!='effective' or not fact.get('status_evidence'):
                raise MvpError('INPUT_INVALID','采购报价须有有效状态依据')
            statuses=self.refs(fact['status_evidence'])
            from .matching import _is_active
            if not all(s['source_id']in quote_sources and _is_active({'fields':{'status':s['value']}})for s in statuses):
                raise MvpError('INPUT_INVALID','采购报价取消/状态冲突或出处不符')
        n=number(fact.get('value'))
        if n is None or n<0 or not any(number(r['value'])==n for r in refs):
            raise MvpError('INPUT_INVALID','采购单价与原格不符')
        currencies=self.refs(fact['currency_evidence'])
        currency=fact.get('currency')
        aliases={'JPY':('JPY','日元','日本JPY','円'),'CNY':('CNY','人民币','RMB'),'USD':('USD','美元')}
        found={c for c,tokens in aliases.items()if any(any(token in x['value']for token in tokens)for x in currencies)}
        if currency not in aliases or found!={currency}or any(r['source_id']not in quote_sources for r in currencies):
            raise MvpError('INPUT_INVALID','采购币种缺明确原格/表头依据')
        def same_record(ref):
            return any(ref['source_id']==q['source_id']and ref['row']==q['row']for q in refs)
        def price_header(ref):
            return (any(ref['source_id']==q['source_id']and ref['column']==q['column']and ref['row']<q['row']for q in refs)
                    and bool(re.search(r'报价|单价|金额|price',ref['value'],re.I)))
        if any(not(same_record(r)or price_header(r))for r in currencies):
            raise MvpError('INPUT_INVALID','币种不能取其他报价行')
        units=self.refs(fact['unit_evidence'])
        unit=fact.get('unit')
        if unit not in UNITS or not fact.get('unit_basis'):
            raise MvpError('INPUT_INVALID','采购单位缺明确说明')
        # The frozen audited mapping supplies semantics; numeric text alone is no unit proof.
        labels={'piece':r'^(?:个|枚|张|件|piece)$|单个|单枚|単品','pack':r'^(?:包|袋|pack)$|整包|单包|パック',
                'box':r'^盒$|整盒|盒装|BOX|\bbox\b','set':r'^套$|套组|セット|\bset\b',
                'carton':r'运输箱|外箱|カートン|\bcarton\b'}
        if (any(x['source_id']not in quote_sources for x in units)or
                any(not same_record(x)for x in units)or not any(re.search(labels[unit],x['value'])for x in units)):
            raise MvpError('INPUT_INVALID','采购单位原文不明确')
        normalized=str(display).strip()
        if currency=='JPY':normalized=re.sub(r'(?:日元|JPY|円)$','',normalized).strip()
        elif currency=='CNY':normalized=re.sub(r'(?:人民币|CNY|RMB|元)$','',normalized).strip()
        else:normalized=re.sub(r'(?:美元|USD)$','',normalized).strip()
        return {**fact,'evidence':refs,'currency_evidence':currencies,'unit_evidence':units,
                'matches_display':number(normalized)==n}

    def facts(self,row,display,invoice=None):
        facts,issues,rejected={},[],[]
        records=self.index.get((row['sheet'],row['row']),[])
        if len(records)>1:
            return {},[{'code':'PRICE_IDENTITY_AMBIGUOUS','field':'scope'}],records
        if not records:return {},[],[]
        record=records[0]
        if set(record.get('scope',{}))!=set(row['scope'])or any(norm(record['scope'][k])!=norm(v)for k,v in row['scope'].items()):
            return {},[{'code':'PRICE_SCOPE_MISMATCH','field':'scope'}],records
        if invoice is not None:
            try:
                facts['invoice_source'],invoice_issues=self.invoice_facts(record['invoice_evidence'],invoice,row['scope'])
                issues+=invoice_issues
            except (MvpError,KeyError,TypeError)as exc:
                issues.append({'code':getattr(exc,'code','INPUT_INVALID'),'field':'invoice_source','message':str(exc)})
        for field in ['duty_rate','vat_rate','purchase_quote']:
            if field not in record:continue
            try:
                fact=record[field]
                facts[field]=self.quote_fact(fact,display,row['scope'])if field=='purchase_quote'else self.rate_fact(fact)
            except (MvpError,KeyError,TypeError)as exc:
                issues.append({'code':getattr(exc,'code','INPUT_INVALID'),'field':field,'message':str(exc)})
                rejected.append({'field':field,'candidate':record[field]})
        return facts,issues,rejected
