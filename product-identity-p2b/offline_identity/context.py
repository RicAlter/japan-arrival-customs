from openpyxl import load_workbook
from openpyxl.utils import column_index_from_string
from .common import text,digest,Rejected


def read_contexts(p1,file,mapping):
    before=digest(file);wanted={r['query']['source']['row']:r for r in p1['rows']};contexts={}
    book=load_workbook(file,read_only=True,data_only=False,keep_links=False)
    try:
        sheet=book.worksheets[0]
        sheet.reset_dimensions()
        maximum=max(column_index_from_string(c) for c in mapping.values())
        for row_num,cells in enumerate(sheet.iter_rows(min_row=2,max_col=maximum),2):
            if row_num not in wanted:continue
            old=wanted[row_num]
            if old['query']['source']['file_sha256']!=before:raise Rejected('本批上下文与P1原始来源哈希不一致')
            if old['query']['source']['sheet']!=sheet.title:raise Rejected('本批上下文工作表与原查询不一致')
            ctx={f:(None if cells[column_index_from_string(c)-1].data_type in ('f','e') else text(cells[column_index_from_string(c)-1].value)) for f,c in mapping.items()}
            if ctx['code_raw']!=old['query']['code_raw'] or ctx['japanese_name']!=old['query']['japanese_name']:raise Rejected('本批原行身份已变化')
            contexts[old['row_id']]=ctx
    finally:book.close()
    if len(contexts)!=len(p1['rows']) or digest(file)!=before:raise Rejected('本批上下文行范围不完整或原件变化')
    return contexts
