"""Only the existing red exception style; no value/formula or metadata changes."""
import copy
from .support import Rejected,key

CELLS={'carton':[('customs','A'),('internal','A')],'origin':[('customs','D'),('internal','B')],
       'japanese_name':[('internal','G')],'internal_name':[('internal','E')],
       'customs_name':[('customs','C'),('customs','I')],'category':[('customs','J'),('internal','L')],
       'material':[('customs','M'),('internal','M')],'business_quantity':[('internal','I')],
       'business_price':[('internal','J')],'business_amount':[('internal','K')],
       'internal_boxes':[('internal','H')],'internal_quantity':[('internal','I')],
       'pieces_per_box':[('internal','N')],'declaration_quantity':[('customs','F')],
       'declaration_price':[('customs','G')],'declaration_amount':[('customs','P')],
       'duty_rate':[('internal',c) for c in ('O','P','Q','R')],
       'vat_rate':[('internal','P'),('internal','R')],'box_tax':[('internal','R')],
       'business_unit':[('internal','I')],'internal_unit':[('internal','I')],
       'declaration_unit':[('customs','F')],'declaration_factor':[('customs','F')]}


def mark_current(data,classified):
    colors=copy.deepcopy(data['colors']);changed=[]
    for index,row in enumerate(classified['rows'],2):
        for task in row['current_tasks']:
            if task['field'] not in CELLS:raise Rejected('当前异常没有允许的原单元格标色位置')
            for kind,col in CELLS[task['field']]:
                address=col+str(index)
                if colors[kind].get(address)!='red':
                    colors[kind][address]='red';changed.append({'table':kind,'cell':address,'field':task['field'],'reason':task['reason']})
    if not changed:return data,[]
    result=dict(data);result['colors']=colors
    if key({k:v for k,v in result.items() if k!='colors'})!=key({k:v for k,v in data.items() if k!='colors'}):
        raise Rejected('异常标色改变了计算内容')
    return result,changed
