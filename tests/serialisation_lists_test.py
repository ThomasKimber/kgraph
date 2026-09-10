from kgraph_fixtures_test import (kgp_pipeline_for_testthings, test_things_data_df)
from rdflib.collection import Collection


def test_serialise_testthings_mapping_fqn_tree(kgp_pipeline_for_testthings):

    assert kgp_pipeline_for_testthings.mapping_object.fully_qualified_names_tree == \
        {'Namespace': '<root>',
        'EntityTypeA': 'Namespace',
        'ComponentB': 'Namespace',
        'AssemblySequence': 'EntityTypeA',
        'ComponentBPackage': 'EntityTypeA',
        'AssemblyDocument': 'Namespace'}

def test_serialise_testthings_mapping_fqn_tree_additional_tests(kgp_pipeline_for_testthings, test_things_data_df):
    rdfgraph = kgp_pipeline_for_testthings.process(test_things_data_df)
    list_heads = list(rdfgraph.query("""
                    SELECT ?head ?label WHERE {
                        ?head rdf:first ?item .
                        ?head rdfs:label ?label
                        FILTER NOT EXISTS {
                            ?other rdf:rest ?head .
                        }
                    }
                    """))
    assert len(list_heads)==2
    collect_results = {}
    for l in list_heads:
        collect_results[l[1].toPython()]=[]
        for c in list(Collection(rdfgraph, l[0])):
            c_label = list(rdfgraph.query(f"""select ?label WHERE {{ {c.n3()} rdfs:label ?label. }}"""))[0][0]
            collect_results[l[1].toPython()].append(c_label.toPython())
    assert collect_results['DoohickeyAssembly']==['Pommel','Spangler','Pommel','Spangler','Shim','Spangler','Spacer','Spangler']
    assert collect_results['WidgetAssembly']==['Harness','Spacer','Shim','HexBolt','AngleThread Y','Shim','Bracket X']
                                                   
