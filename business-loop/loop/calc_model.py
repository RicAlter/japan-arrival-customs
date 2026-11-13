"""A03 sparse fields for the B00 adapter; no inference in saved confirmations."""
from copy import deepcopy
from collections import Counter
import re
from a_confirm import model as original
CONFIRMED=original.CONFIRMED
value=original.value
identity_context=original.identity_context
effective_fields=original.effective_fields
def recheck(source,sheet,baseline,state):
    fields=effective_fields(baseline,state);rows=[]
    for f in fields.values():
        if f['field']!='pieces_per_box':continue
        active=f['confirmed'] and f.get('identity_context_hash')==identity_context(fields,f['row_id'])
        rows.append({'row_id':f['row_id'],'h_cell':f['cell'],'u_cell':None,'mode':'manual',
            'pieces_per_box':f['value']['value'] if active else None,'difference_jpy':None,
            'status':'new_roles_and_conversion_confirmed' if active else 'calculation_scope_unconfirmed',
            'notice':'仅承接精确价格角色及明确换算范围；不伪造旧100JPY核价结果、不授予专业批准'})
    rows.sort(key=lambda r:(int(re.search(r'\d+$',r['h_cell'])[0]),r['row_id']))
    return fields,{'rows':rows,'counts':dict(Counter(r['status'] for r in rows)),'groups':[],
        'phase':'calculation_review','formal_output':False,'can_enter_b':False}
