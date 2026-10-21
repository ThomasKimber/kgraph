import os
from pathlib import Path
current_dir = Path(__file__).parent

from rdflib import Graph, Literal, URIRef
from rdflib.namespace import SKOS, RDF, RDFS
from pyshacl import validate

import pytest
import pandas as pd
import json
import networkx as nx

from importlib import resources

from kgraphing import declarations
from kgraphing.ingest import schemamapping, kgpipeline
from kgraphing import nxproperties
from kgraphing.store import kgstore, metadata, rdfquery
from kgraphing import ontologies


from kgraph_fixtures_test import (raw_data_df, 
                                  schema_mapping_object, 
                                  serialised_graph, 
                                  kgp_pipeline, 
                                  kgp_graph, 
                                  in_memory_store, 
                                  toy_graph, 
                                  ontology_cache, 
                                  rdf2dict_of_serialised_graph)

def test_instantiate_schema_mapping_isdataframe(schema_mapping_object):
    """Instantiate a schema_mapping object"""
    S = schema_mapping_object
    assert isinstance(S, schemamapping.SchemaMapping)

def test_serialise_data_isgraph(serialised_graph):
    g = serialised_graph
    assert isinstance(g, Graph)

def test_serialised_concept_count(serialised_graph):
    """In an pre-prepared list of definitions, the expected number of Concepts is 26"""
    extracted_concepts=[s for s,_,_ in serialised_graph.triples((None, RDF.type, SKOS.Concept))]
    extracted_concept_names = [
        n
        for s in extracted_concepts
        for _,_,n in serialised_graph.triples((s, declarations.KGNAM.FullyQualifiedName, None))
    ]

    assert len(extracted_concept_names) == 32
    assert sorted(extracted_concept_names) == [Literal(n) 
                                       for n in ['Vocabularies.Test.TestAlphabetVocab.Apple',
                                                 'Vocabularies.TestAlphabetVocab.Animal', 'Vocabularies.TestAlphabetVocab.Apple',
                                                 'Vocabularies.TestAlphabetVocab.Artifact',
                                                'Vocabularies.TestAlphabetVocab.Banana', 'Vocabularies.TestAlphabetVocab.Cat',
                                                'Vocabularies.TestAlphabetVocab.Dog', 'Vocabularies.TestAlphabetVocab.Elephant',
                                                'Vocabularies.TestAlphabetVocab.Fox', 'Vocabularies.TestAlphabetVocab.Fruit',
                                                'Vocabularies.TestAlphabetVocab.Goat', 'Vocabularies.TestAlphabetVocab.House',
                                                'Vocabularies.TestAlphabetVocab.Imagination', 'Vocabularies.TestAlphabetVocab.Jungle',
                                                'Vocabularies.TestAlphabetVocab.King', 'Vocabularies.TestAlphabetVocab.Lemon',
                                                'Vocabularies.TestAlphabetVocab.Monarch', 'Vocabularies.TestAlphabetVocab.Mouse',
                                                'Vocabularies.TestAlphabetVocab.Nest', 'Vocabularies.TestAlphabetVocab.Octopus',
                                                'Vocabularies.TestAlphabetVocab.Parrot', 'Vocabularies.TestAlphabetVocab.Queen',
                                                'Vocabularies.TestAlphabetVocab.Rain', 'Vocabularies.TestAlphabetVocab.Structure',
                                                'Vocabularies.TestAlphabetVocab.Sun', 'Vocabularies.TestAlphabetVocab.Train', 
                                                'Vocabularies.TestAlphabetVocab.Umbrella', 'Vocabularies.TestAlphabetVocab.Village', 
                                                'Vocabularies.TestAlphabetVocab.Wheel', 'Vocabularies.TestAlphabetVocab.Xylophone', 
                                                'Vocabularies.TestAlphabetVocab.Yak', 'Vocabularies.TestAlphabetVocab.Zebra',
                                                ]
                                                                                    ]
    
def test_post_schema_mapping_shacl_validation(serialised_graph):
    ont = Graph()
    kgnam_file = str(resources.files(ontologies) / os.path.normpath("kgnam.owl"))
    ont.parse(kgnam_file)
    conforms, results_g, results_t = validate(
                                            serialised_graph, 
                                            shacl_graph=declarations.KGNAM_SHAPES_G, 
                                            ont_graph=ont, 
                                            inference='rdfs', 
                                            abort_on_first=False, 
                                            allow_infos=False, 
                                            allow_warnings=False, 
                                            meta_shacl=False, 
                                            advanced=False, 
                                            js=False, 
                                            debug=False
                                        )
    assert conforms == True

def test_kgpipeline_is_a_pipeline(kgp_pipeline):
    assert isinstance(kgp_pipeline, kgpipeline.KGraphPipeline)

def test_kgpipeline_graph_is_a_graph(kgp_graph):
    assert isinstance(kgp_graph, Graph)

def test_kgpipeline_graph_validation_is_true(kgp_pipeline, kgp_graph):
    assert kgp_pipeline.shacl_validation_results[0][0]==True


def test_kgpipeline_graph_matches_alt_graph(kgp_graph, serialised_graph):
    assert len(kgp_graph)==len(serialised_graph)

def test_create_in_memory_store_and_populate_with_metadata_update_scenario_union(in_memory_store, toy_graph):
    toy_graph_stored = in_memory_store.update_graph(toy_graph, scenario=kgstore.MergePolicy.UNION)

def test_create_in_memory_store_and_populate_with_metadata_update_scenario_full_replace(in_memory_store, toy_graph):
    toy_graph_stored = in_memory_store.update_graph(toy_graph)
    toy_graph_stored.add((URIRef('http://kgraph.foo.bar#example3'), 
                URIRef('http://kgraph.foo.bar#predicate'), 
                URIRef('http://kgraph.foo.bar#example4')))
    toy_graph_stored = in_memory_store.update_graph(toy_graph, scenario=kgstore.MergePolicy.FULL_REPLACE)

def test_create_in_memory_store_and_populate_with_metadata_update_scenario_entity_replace(in_memory_store, toy_graph):
    toy_graph_stored = in_memory_store.update_graph(toy_graph)
    toy_graph_stored.add((URIRef('http://kgraph.foo.bar#example3'), 
                URIRef('http://kgraph.foo.bar#predicate'), 
                URIRef('http://kgraph.foo.bar#example4')))
    toy_graph_stored = in_memory_store.update_graph(toy_graph, scenario=kgstore.MergePolicy.ENTITY_REPLACE)

def test_create_in_memory_store_and_populate_with_metadata_update_scenario_property_replace(in_memory_store, toy_graph):
    toy_graph_stored = in_memory_store.update_graph(toy_graph)
    toy_graph_stored.add((URIRef('http://kgraph.foo.bar#example3'), 
                URIRef('http://kgraph.foo.bar#predicate'), 
                URIRef('http://kgraph.foo.bar#example4')))
    toy_graph_stored = in_memory_store.update_graph(toy_graph, scenario=kgstore.MergePolicy.PROPERTY_REPLACE)
    


    gmeta_packet_graph = metadata.NamedGraphMetaData(
            uri = toy_graph_stored.identifier, 
            title = "Toy Graph", 
            label = "Toy Graph", 
            language = "en", 
            description = """A minimal graph containing a single triple for testing purposes""", 
            metadata_type = metadata.MetaDataType.dataset
        ).to_graph()
    in_memory_store.update_graph(gmeta_packet_graph, 
                                 "http://kgraph.foo.bar/metadata", 
                                 scenario=kgstore.MergePolicy.ENTITY_REPLACE)
    stored_graphs = in_memory_store.list_graphs()
    assert toy_graph_stored.identifier in stored_graphs
    assert URIRef("http://kgraph.foo.bar/metadata") in stored_graphs

def test_clear_graph(in_memory_store, toy_graph):
    toy_graph_stored = in_memory_store.update_graph(toy_graph)
    assert len(list(toy_graph_stored.triples((None, None, None)))) == 1
    in_memory_store.clear_graph(toy_graph_stored.identifier)
    assert len(list(toy_graph_stored.triples((None, None, None)))) == 0

def test_drop_graph(in_memory_store, toy_graph):
    toy_graph_stored = in_memory_store.update_graph(toy_graph)
    assert len(list(toy_graph_stored.triples((None, None, None)))) == 1
    in_memory_store.drop_graph(toy_graph_stored.identifier)
    assert toy_graph_stored.identifier not in in_memory_store.list_graphs()

def test_get_graph_metrics(in_memory_store, toy_graph):
    toy_graph_stored = in_memory_store.update_graph(toy_graph)
    metrics = in_memory_store.get_graph_metrics(toy_graph_stored)
    assert set(metrics.keys())=={"triple_count", "predicate_count", "type_count", "untyped_count"}
    assert metrics["triple_count"]==1
    assert len(metrics["predicate_count"])==1
    assert len(metrics["type_count"])==0
    assert metrics["untyped_count"]==1

def test_ontology_cache_instantiation_and_file_registration(ontology_cache):
    kgnam_path = str(resources.files(ontologies) / os.path.normpath("kgnam.owl"))
    OC = ontology_cache
    OC.register("https://kgraph.foo/onto/kgnam#", 
            False, 
            kgnam_path)
    # Test that a file exists in the cache and that its name matches the registry
    v,m,o = OC.cross_check_registry_cache()
    assert len(o)==0
    assert len(m)==0
    assert len(v)==1

def test_rdf2d_instantiation(rdf2dict_of_serialised_graph):
    assert len(rdf2dict_of_serialised_graph.entities)==170
    assert len(rdf2dict_of_serialised_graph.relations)==12

def test_rdf2d_cache_enrichment(rdf2dict_of_serialised_graph):
    rdf2dict_of_serialised_graph.enrich_metadata()
    assert len(rdf2dict_of_serialised_graph.ontology_cache.registry)==5
    assert len(rdf2dict_of_serialised_graph.entities)==299 or len(rdf2dict_of_serialised_graph.entities)==297
    assert len(rdf2dict_of_serialised_graph.relations)==23
    


def test_create_prepared_query():
    pq = rdfquery.QueryAPI(
        """SELECT ?s ?p ?o WHERE { ?s ?p ?o. }""",
        """Select everything from the graph""",
        {},
        None
    )
    assert [str(p) for p in pq.prepared_query.algebra['PV']]==['s','p','o']

def test_execute_prepared_query(toy_graph):
    pq = rdfquery.QueryAPI(
        """SELECT ?s ?p ?o WHERE { ?s ?p ?o. }""",
        """Select everything from the graph""",
        {},
        None
    )
    results = pq.execute(toy_graph,{})
    assert isinstance(results, list)
    assert len(results)==1
    assert len(results[0])==3


def test_execute_prepared_query_with_bindings(toy_graph):
    pq = rdfquery.QueryAPI(
        """SELECT ?s ?p ?o WHERE { ?s ?p ?o. }""",
        """Select everything from the graph""",
        {"s" : URIRef},
        None
    )
    results = pq.execute(toy_graph,{}) # execute with no bindings
    bindings={"s" : URIRef('http://kgraph.foo.bar#example1')}
    binding_test = pq.validate_bindings(bindings)
    assert binding_test==(True, [])
    results = pq.execute(toy_graph,bindings) # execute with s bound
    assert isinstance(results, list)
    assert len(results)==1
    assert len(results[0])==3
