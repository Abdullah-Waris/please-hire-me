import pytest
from hireme.material_ledger import search_materials
from hireme.materials import import_material, review_material


def test_source_search_reaches_old_sources_and_literal_unicode_excerpts(store):
    source = import_material(store, 'Synthetic STRAßE excerpt with literal 100%_value.'.encode(), 'old-notes.txt', 'context')
    store.db.execute("UPDATE materials SET created='2000-01-01' WHERE id=?", (source['id'],))
    for i in range(30): import_material(store, f'Newer synthetic excerpt number {i} for review.'.encode(), f'new-{i}.txt', 'context')
    assert source['id'] not in {row['id'] for row in search_materials(store)['materials']}
    before=store.snapshot(); changes=store.db.total_changes
    for term in ('STRASSE', '100%_value', 'old-notes'):
        result=search_materials(store, search=term, offset=100)
        assert result['total']==1 and result['offset']==0 and result['materials'][0]['id']==source['id']
        assert result['library_total']==31
    assert search_materials(store,search='not present')['materials']==[]
    assert store.snapshot()==before and store.db.total_changes==changes


def test_source_approval_filters_do_not_treat_unapproved_roles_as_approved(store):
    for role in ('personal', 'style', 'reference'):
        source=import_material(store, f'Synthetic {role} excerpt long enough for review.'.encode(), role+'.txt', 'context')
        review_material(store,source['id'],source['text'],role,True)
    source=import_material(store,b'Unapproved synthetic excerpt long enough for review.','unapproved.txt','context')
    review_material(store,source['id'],source['text'],'style',False)
    assert search_materials(store,status='approved')['total']==3
    assert search_materials(store,status='review')['total']==1
    for role in ('personal','style','reference'):
        result=search_materials(store,status=role)
        assert result['total']==1 and result['materials'][0]['confirmed']==1
    snapshot=store.snapshot(material_search='Unapproved',material_status='review')
    assert snapshot['material_count']==1 and snapshot['material_total']==4
    assert snapshot['material_search']=='Unapproved' and snapshot['material_status']=='review'


@pytest.mark.parametrize('kwargs',[{'search':None},{'search':'x'*201},{'status':'unknown'},{'offset':True},{'offset':-1},{'offset':1000001},{'limit':0},{'limit':101}])
def test_source_search_rejects_invalid_bounds(store,kwargs):
    with pytest.raises(ValueError): search_materials(store,**kwargs)
