"""Load existing flow unchanged in private namespace; replace only adapter seams."""
import sys,types
from . import support,ROOT,REPO,price_input
from .support import load_module
NAME='packloop.flow';package=types.ModuleType(NAME);package.__path__=[];sys.modules[NAME]=package
sys.modules[NAME+'.support']=support
source=REPO/'business-loop/loop'
updates=price_input.load_updates(NAME+'.updates',source/'updates.py')
OriginalUpdates=updates.Service
class Updates(OriginalUpdates):
    def __init__(self,root):
        super().__init__(root)
        workflow=support.load(self.owner['workflow'])
        if workflow.get('schema')!='catalogue-19-workflow/1':raise support.Rejected('新包装候选只接明确登记的19列workflow')
        snapshot=support.Path(workflow['catalogue_snapshot'])
        support.check_hashes({str(snapshot):workflow['catalogue_snapshot_sha256']})
        catalogue=support.load(snapshot);support.check_hashes({catalogue['database']:catalogue['sha256']})
updates.Service=Updates
sys.modules[NAME+'.prices']=load_module(NAME+'.prices',source/'prices.py')
base_review=load_module(NAME+'.base_review',source/'review.py',{
    "oldplan=load(parent/'technical/authoring-plan.json')":
    "oldplan=load(parent/'technical/authoring-plan.json') if (parent/'technical/authoring-plan.json').exists() else {}"})
from . import review
review.base=base_review;review.legacy_recalculate=base_review.recalculate;base_review.current_price=review.current_price
base_review.EDIT=review.EDIT;base_review.recalculate=review.recalculate
sys.modules[NAME+'.review']=review
base_book=load_module(NAME+'.base_book',source/'review_book.py')
from . import review_book
review_book.base=base_book;sys.modules[NAME+'.review_book']=review_book
load_module(NAME+'.calc_model',source/'calc_model.py')
compute=load_module(NAME+'.compute',source/'compute.py',{"NAME='loop._frozen_basis'":"NAME='packloop.flow._frozen_basis'"})
delivery=load_module(NAME+'.delivery',source/'delivery.py')
cli=load_module(NAME+'.cli',source/'cli.py')
