"""Specific product labels only; no parent-YD blanket application."""
def kind(spec,jp):
    rules=[('拍立得',['拍立得','ポラショット','ポラロイド']),('明信片',['明信片','ポストカード']),('贴纸',['贴纸','ステッカー','ｽﾃｯｶｰ']),('相卡',['相卡','ブロマイド','フォトカード']),('吧唧',['吧唧','缶バッジ']),('立牌',['立牌','アクリルスタンド']),('卡片',['卡片','カード'])]
    for source in [str(spec or ''),str(jp or '')]:
        for label,words in rules:
            if any(w in source for w in words):return label
    return None
def matches(kind,label,spec):
    return bool(label and (kind and kind in label or label not in {'其他','本体','主体'} and len(label)>=2 and label in str(spec or '')))
