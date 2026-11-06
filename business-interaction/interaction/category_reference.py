"""Business type suggestions from function evidence, never material rewriting."""
import re,unicodedata
def suggest(row):
    jp=unicodedata.normalize('NFKC',str(row.get('jp') or ''))
    spec=unicodedata.normalize('NFKC',str(row.get('spec') or ''))
    old=str(row.get('ai_category') or '')
    material=str(row.get('ai_material') or '')  # Read as context; never modified.
    t=jp+' '+spec
    def result(value,basis,pending=False):return {'value':value,'basis':basis,'pending':pending,'old_reference':row.get('ai_category'),'material_unchanged':True,'human_confirmation':False}
    # Actual Japanese function wins over names of all goods in the YD link.
    if re.search(r'缶バッ[ジチ]|キャラバッジ|カンバッジ|アクリルバッジ',jp) or old in {'吧唧','线稿吧唧','徽章'}:
        return result('徽章','具体单品为徽章；历史业务表使用徽章')
    if 'クリアファイル' in jp or old=='文件夹':return result('文件夹','具体用途为文件夹')
    if re.search(r'パスケース|カードケース|カードホルダー|フォトケース',jp):return result('卡套','具体用途为卡片收纳；不按キーホルダー一律写挂件')
    if re.search(r'アクリル(?:[^／/]{0,16}スタンド|ボード|ブロック|フィギュア|プレート|クリップ|マスコット|パネル)|どこスタ',jp) or old in {'立牌','亚克力立板','亚克力立牌','亚克力块','亚克力展示牌','亚克力夹子'}:
        return result('站牌','按用户截图：立牌/亚克力砖/立板/亚克力夹使用站牌')
    if 'コースター' in jp or '杯垫' in old:
        if 'アクリル' in jp or old=='亚克力杯垫':return result('挂牌','用户截图明确亚克力杯垫称挂牌')
        if 'ペーパー' in jp or material=='纸':return result('收藏卡片','用户截图明确纸质杯垫称收藏卡片')
        if material and '纸' not in material and '亚克力' not in material:return result('摆件','用户截图明确非纸质/非亚克力杯垫称摆件')
        return result(None,'杯垫材料范围不清，不能选择收藏卡片/挂牌/摆件',True)
    if re.search(r'ブロマイド|フォトカード|ポストカード|イラストカード|クリアカード|アクリルカード|コレクションカード|色紙|証明写真|ポラショット|Ani-Frame|REPLICA GENGA|ぱしゃ',jp,re.I) or old in {'拍立得','相卡','卡片','亚克力卡','插画卡','闪卡','四格相卡','色纸','透卡','明信片','亚克力色纸','复制原画'}:
        return result('收藏卡片','按用户截图与历史用途：纸/塑料收藏卡片统一收藏卡片；材质原文另存')
    if 'ステッカー' in jp or 'シール' in jp or old=='贴纸':return result('贴纸','具体用途为贴纸')
    if 'Tシャツ' in jp:return result('T恤','日方单品明确Tシャツ，历史表使用T恤')
    if 'スカーフ' in jp:return result('围巾','日方单品明确スカーフ')
    if re.search(r'ぬいぐるみ|ぬい.*マスコット',jp) or old in {'毛绒','毛绒挂件'}:
        return result(None,'毛绒需看图确认链子/卡套/填充玩具及人物动物、适用年龄；不推定15岁',True)
    if 'クッション' in jp:return result('靠垫','具体用途为クッション，不按毛绒一律称挂件')
    if 'ヘアクリップ' in jp or old=='橡胶发夹':return result('发夹','日方明确发夹用途；不同于亚克力展示夹')
    if re.search(r'キーホルダー|チャーム',jp) or old in {'挂件','亚克力挂件'}:
        return result('挂件','单品功能为钥匙扣/挂饰；仍为参考，卡套/毛绒优先另判',True)
    if 'フィギュア' in jp or '模型' in spec:return result('精细收藏模型','具体商品为收藏模型/手办')
    if 'ポーチ' in jp or '巾着' in jp:return result('收纳袋','具体用途为收纳袋/束口袋')
    if 'パスポートケース' in jp:return result('收纳套','日方单品明确护照收纳套，不认作站牌或卡片')
    if 'トートバッグ' in jp:return result('手提袋','具体用途为手提袋')
    if 'マグネット' in jp:return result('冰箱贴','单品明确磁吸贴件')
    return result(None,'具体用途尚不清楚，不能仅凭材料或链接商品名确定品类',True)
