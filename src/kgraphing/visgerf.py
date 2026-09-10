"""Methods for generating a visualisation graph
from a Gerf object"""
from typing import Optional
from collections.abc import Callable
from networkx import MultiDiGraph

from rdflib import Graph, Literal, URIRef, BNode
from rdflib.namespace import RDF, RDFS

from kgraphing.gerf import Gerf, ObservedEntity, ObservedRelationClass
from kgraphing.declarations import RDFObjectAtom


class VisGerf:

    def __init__(self, 
                 gerf_object : Gerf):
        self.gerf = gerf_object

    

    def gerf_to_base_nx(
            self,
            gerf_object : Gerf,
            include_node_function : Optional[Callable],
            include_edge_function : Optional[Callable],
            node_properties_function : Optional[Callable]=None, 
            edge_properties_function : Optional[Callable]=None, 
            ) -> MultiDiGraph:
        """This is the default graph-generation recipe.
        A function defines the 'closure' of the graph, 
        such that no nodes can be visualised outside of 
        that closure. An additional edge-inclusion 
        function exists that can trim out unwanted edges.
        At creation time, the nodes and edges are populated 
        with information via a suitably called properties function."""
        base_g = MultiDiGraph()
        node_includes=[]
        non_entity_nodes=[]

        if include_node_function is None:
            include_node_function=self._default_include_node_function

        if include_edge_function is None:
            include_edge_function=self._default_include_edge_function

        if node_properties_function is None:
            node_properties_function=self._default_node_properties_function

        if edge_properties_function is None:
            edge_properties_function=self._default_edge_properties_function


        # Define the 'closure' of the graph
        for k,e in self.gerf.entities.items():
            if include_node_function(self.gerf, k):
                node_includes.append(k)
            else:
                non_entity_nodes.append(k)

        for k in node_includes:
            base_g.add_node(k, **node_properties_function(self.gerf, k))
            for predicate, object_set in self.gerf.entities[k].interactions.items():
                for element in object_set:
                    if element in node_includes: # Test the other end is present in node_includes
                        if include_edge_function(self.gerf, k, predicate, element):
                            base_g.add_edge(k, element, **edge_properties_function(self.gerf, k, predicate, element))

        #for k in non_entity_nodes:
        #    base_g.add_node(k, **{"node_type" : "weird, non-entity-node"})

        return base_g

    @staticmethod
    def _default_include_node_function(gerf_object, identifier):
        empty_node=ObservedEntity(identifier=None, order=None, gerf_object=gerf_object)
        test_node = gerf_object.entities.get(identifier, empty_node)
        tests = [
                test_node.identifier in gerf_object.entities.keys(), 
                test_node.order==0, 
                test_node.term in (URIRef, BNode, Literal)
                 ]
        return all(tests)
    
    @staticmethod
    def _default_include_edge_function(gerf_object, identifier, predicate, element):
        tests = [
                identifier in gerf_object.entities.keys(), 
                element in gerf_object.entities.keys(), 
                predicate in gerf_object.relations.keys(),
                VisGerf._predicate_is_subclass_leaf(gerf_object, identifier, predicate, element)                # include only predicates that are subClass leaves
                ]
        return all(tests)

    @staticmethod
    def _predicate_is_subclass_leaf(gerf_object, identifier, predicate, element):
        sub_properties = set([s 
                                for s,p,o in gerf_object.total_graph.triples((None, RDFS.subPropertyOf, predicate)) 
                                if s!=o])
        # Select most specific active sub-property that exists between this pair of nodes
        if any({p in sub_properties for s,p,o in gerf_object.total_graph.triples((identifier, None, element))}):
            return False
        else:
            return True





    @staticmethod
    def _default_node_properties_function(gerf_object, identifier):
        property_dict = {}
        EmptyObject = ObservedEntity(identifier=None, order=None, gerf_object=gerf_object)
        property_dict['label']=str(next(iter(gerf_object.entities.get(identifier, EmptyObject).interactions.get(RDFS.label,{identifier.n3(namespace_manager=gerf_object.source_graph.namespace_manager)}))))
        property_dict['click']=gerf_object.entities.get(identifier, EmptyObject).to_html()
        
        return property_dict
    
    @staticmethod
    def _default_edge_properties_function(gerf_object, identifier, predicate, element):
        # Need to trim relations that are duplicated due to subclassed relation-definitions
        property_dict = {}
        EmptyObject = ObservedEntity(identifier=None, order=None, gerf_object=gerf_object)
        relation_def = gerf_object.entities.get(predicate, EmptyObject)
        property_dict['label']=predicate.n3(namespace_manager=gerf_object.source_graph.namespace_manager)
        property_dict['click']=relation_def.to_html()
        property_dict['predicate']=gerf_object.entities.get(predicate, EmptyObject).identifier
        return property_dict
    
