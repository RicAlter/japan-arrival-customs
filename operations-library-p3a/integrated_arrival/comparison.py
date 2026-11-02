"""Semantic fingerprint for the two existing report formats, read-only."""
from openpyxl import load_workbook
from .support import key


def workbook_snapshot(path):
    raw=load_workbook(path,data_only=False,keep_links=False)
    cached=load_workbook(path,data_only=True,keep_links=False)
    try:
        sheets=[]
        for sheet,values in zip(raw,cached):
            cells=[]
            for row in sheet:
                cells.append([[c.value,c.data_type,values[c.coordinate].value,list(c._style) if c.has_style else None,c.number_format] for c in row])
            sheets.append({'title':sheet.title,'rows':sheet.max_row,'cols':sheet.max_column,'cells':cells,
                'freeze':sheet.freeze_panes,'state':sheet.sheet_state,'gridlines':sheet.sheet_view.showGridLines,
                'merges':list(map(str,sheet.merged_cells)),
                'row_dimensions':{str(k):[v.height,v.hidden] for k,v in sheet.row_dimensions.items()},
                'column_dimensions':{k:[v.width,v.hidden] for k,v in sheet.column_dimensions.items()},
                'header':str(sheet.oddHeader),'footer':str(sheet.oddFooter)})
        # description is an execution-specific state hash. Creation/save times
        # and that hash can differ across isolated runs; worksheet data cannot.
        return {'sheets':sheets,'controlled_title':raw.properties.title,'external_links':bool(raw._external_links),
                'defined_names':list(raw.defined_names)}
    finally:raw.close();cached.close()


def compare(left,right):
    a=workbook_snapshot(left);b=workbook_snapshot(right)
    return {'equal':a==b,'left_semantic_sha256':key(a),'right_semantic_sha256':key(b),
            'includes':['all_cells','formulas','cached_values','styles','number_formats','sheet_order','row_order','weights',
                        'F','remarks','YD','dimensions','controlled_headers','external_link_flags'],
            'excluded':['execution_state_description','document_creation_save_timestamps']}
