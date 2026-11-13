"""Source-backed reference selection; never calculates packaging quantities."""
import re

TYPES = {'stand': ('立牌','立板','アクリルスタンド'), 'acrylic_card': ('亚克力卡','アクリルカード'),
 'block': ('亚克力块','アクリルブロック'), 'badge': ('吧唧','徽章','缶バッジ'),
 'photo': ('拍立得','相卡','插画卡','卡片','ブロマイド','イラストカード','Ani-Frame'),
 'sticker': ('贴纸','ステッカー'), 'holder': ('卡套','カードホルダー'),
 'charm': ('挂件','キーホルダー','チャーム'), 'paperboard': ('色纸','色紙'),
 'postcard': ('明信片','ポストカード'), 'clear': ('透卡','クリアカード'),
 'file': ('文件夹','クリアファイル'), 'coaster': ('杯垫','コースター'), 'sleeve': ('收纳套','収納ケース')}

def kinds(spec):
    found={k for k,words in TYPES.items() if any(w in spec for w in words)}
    if 'acrylic_card' in found:found.discard('photo')
    if re.search('卡套组',spec):found.discard('holder')
    return found

def material(spec, raw, history=()):
    if not raw:return {'value':None,'status':'missing','raw':raw}
    wanted=kinds(spec);matches=[]
    for part in re.split('[，,；;\n]',raw):
        if re.search('[:：]',part):label,value=re.split('[:：]',part,maxsplit=1)
        else:
            match=re.fullmatch(r'(.+?)(亚克力|ABS树脂|ABS|马口铁|PET[、/]PP|PET|PP|纸|聚酯纤维|聚酯|PU/PVC)',part.strip())
            if not match:continue
            label,value=match.groups()
        if wanted & kinds(label):matches.append(value.strip())
    unique=set(matches)
    if len(unique)==1:return {'value':matches[0],'status':'explicit_label','raw':raw}
    if len(unique)>1:return {'value':raw,'status':'conflict','raw':raw}
    if len(wanted)>1:return {'value':raw,'status':'unresolved','raw':raw,'reason':'multiple_product_types_in_specification'}
    for token,value in [('拍立得','纸'),('立牌','亚克力')]:
        if token in spec and value in raw:return {'value':value,'status':'user_rule','raw':raw,'rule':token}
    for h in history:
        if h.get('verified') is True and h.get('source') and h.get('term') in spec and h.get('material') in raw:
            return {'value':h['material'],'status':'history_reference','raw':raw,'evidence':h}
    mixed=bool(re.search('[，,、:：]',raw))
    return {'value':raw,'status':'unresolved' if mixed else 'source_reference','raw':raw}

def packaging(spec, raw):
    if not raw:return {'value':None,'raw':raw,'status':'missing'}
    parts=re.split('[，,；;\n]',raw);clauses=[]
    for part in parts:
        if clauses and re.match(r'\s*[（(]?每(?:包|盒|套|袋)',part):clauses[-1]+='，'+part
        else:clauses.append(part)
    matched=[p for p in clauses if kinds(spec)&kinds(p)]
    return {'value':matched[0] if len(matched)==1 else raw,'raw':raw,
            'status':'specific_fragment' if len(matched)==1 else 'original_reference','calculated_count':None}
