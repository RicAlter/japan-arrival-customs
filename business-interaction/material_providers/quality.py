"""Reject page chrome/code in live and cached material evidence."""
import re

def material_quality(value):
    return isinstance(value,str) and bool(value.strip()) and not re.search(r'@context|@type|schema\.org|お気に入り|ログイン|カートに|作品一覧|(?:^|[\n；;])\s*(?:Size|Color|Features|Art by|Copyright)\b|(?:^|[\n；;])\s*(?:商品仕様|PKG形態|対象年齢|著作権)|<[/!a-zA-Z]|https?://|"(?:offers|priceCurrency|availability)"\s*:',value,re.I)
