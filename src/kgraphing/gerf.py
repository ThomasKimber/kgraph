"""Utility for converting rdflib graphs into dictionary
representations, and (at some point in the future) back again."""

from typing import Optional, Self, Any
from dataclasses import dataclass, asdict, field
import json
import uuid
import os

from xml.etree import ElementTree as ET
from urllib.parse import urldefrag
from rdflib import Graph, Literal, URIRef, BNode
from rdflib.term import Identifier, Node
from rdflib.namespace import RDF, RDFS
from rdflib.parser import Parser
from rdflib.plugin import register, PluginException
from rdflib.exceptions import ParserError
from urllib.error import HTTPError, URLError

from owlrl import DeductiveClosure, RDFS_Semantics

from kgraphing.ocache import OntologyCache
from kgraphing.declarations import KGNAM



@dataclass(kw_only=True)
class GerfThing:
    identifier: Node
    full_name: Optional[str] = None
    short_name: Optional[str] = None
    gerf_object : Any

    def to_dict(self):
        return asdict(self)


@dataclass(kw_only=True)
class ObservedRelationClass(GerfThing):
    """The ObservedRelationClass class collates information about
    how a Relation is used within a given context (graph).
    This can be compared against expected usage for validation
    but is also referenced when unpacking contents from
    one representation to another."""

    _observed_rdf_subject_terms: set[type[Identifier]] = field(default_factory=set)
    _observed_rdf_object_terms: set[type[Identifier]] = field(default_factory=set)
    _observed_rdf_subject_classes: set[Identifier] = field(default_factory=set)
    _observed_rdf_object_classes: set[Identifier] = field(default_factory=set)
    _observed__count: int = 0
    order: int

    def to_dict(self):
        return super().to_dict()


@dataclass(kw_only=True)
class ObservedEntity(GerfThing):
    """The ObservedEntity class collates information about
    entities observed within a given context and stores
    meta-data collected about them.
    It will have a wider scope than the raw-graph-dict, in
    that non-subject entities (objects and literals)
    will be identified here, while only subjects are keyed in
    the graph_dict
    """

    _observed_rdf_terms: set[type[Identifier]] = field(default_factory=set)
    _observed_rdf_classes: set[URIRef] = field(default_factory=set)
    _observed_outgoing_relations: set[URIRef] = field(default_factory=set)
    _observed_incoming_relations: set[URIRef] = field(default_factory=set)
    interactions: dict[URIRef, Identifier] = field(default_factory=dict)
    order: int

    @property
    def term(self):
        if len(self._observed_rdf_terms) == 1:
            [_term] = self._observed_rdf_terms
        elif len(self._observed_rdf_terms) > 1:
            assert False
        else:  # len(self._observed_rdf_terms)==0
            _term = None

        return _term

    def to_dict(self):
        return {**super().to_dict(), **{"term": self.term}}

    def html_stub(self):
        # Define a common, reusable header that can be emitted when requested that represents 
        # this thing - Often, it will be a simple <a href> element - but where the object is
        # more interesting (e.g. a list) then returned content might be more involved.

        # Later, we might swap in some kind of configuration options to help control this
        # representation/emission on a more modular "plugin" basis. e.g. 
        label = None
        if isinstance(self.identifier, (URIRef, BNode)):
            label_set = self.interactions.get(RDFS.label, set())
            name_set = self.interactions.get(KGNAM.Name, set())
            fqn_name_set = self.interactions.get(KGNAM.FullyQualifiedName, set())
            type_set = self.interactions.get(RDF.type, set())
            for s in [label_set, name_set, fqn_name_set]:
                if len(s)>0:
                    label = next(iter(s))
                    break
            if label is None:
                label = self.identifier.n3(namespace_manager=self.gerf_object.total_graph.namespace_manager)
            return f"<a href={str(self.identifier)}>{label}</a>"
        elif isinstance(self.identifier, Literal):
            return str(self.identifier.toPython())


    def to_html(self):
        rows = []
        for k, v_set in self.interactions.items():
            for e, v in enumerate(v_set):
                v_stub = self.gerf_object.entities.get(self.identifier, 
                                                       ObservedEntity(identifier=None, 
                                                                      order=None, 
                                                                      gerf_object=self)
                                                                      ).html_stub()

                if e == 0:
                    rows.append(f"""<tr>
                                    <td rowspan="{len(v_set)}">{str(k)}</td>
                                    <td> {v_stub} </td>
                                </tr>
                                """)
                else:
                    rows.append(f"""<tr>
                                    <td> {v_stub} </td>
                                </tr>
                                """)

        return f"""<table>{"".join(rows)}</table>"""


class Gerf:
    """The Gerf class translates an rdflib Graph object
    into a structured object containing Entities and Relations dictionaries.
    These dictionaries are keyed on their URIs
    
    A Graph G consists of { E, R, F }
    where
    E is a set of Entities contained within the graph
    R is the set of Relations that define connection types
    F is the set of Facts, expressed as (h, r, t)
    where
    (h ∈ E, r ∈ R, t ∈ E)

    For convenience, the Entities object contains a property
    called `interactions` that contains a relation-keyed 
    dictionary listing all facts expressed in the graph.

    This provides a common method for extracting content
    from the graph in an Entity-centric way.
    """

    def __init__(self, g: Graph, cache: OntologyCache):
        self.source_graph=Gerf.copy_graph(g) # Store a copy of the original graph used to instantiate the object
        self.ontology_graph=Graph()
        self.inferred_graph=Graph()
        self.total_graph=Graph()
        self.relations = (
            {}
        )  # A dictionary keyed on predicates - provides graph-level meta-data over the observed usage of the predicate
        self.entities = (
            {}
        )  # A dictionary keyed on subject - this differs from the raw_graph_dict in that it collects observations across the graph
        # It might be worth stripping this out later, I'm not 100% convinced this is doing anything meaningful that the raw_graph_dict isn't
        self.ontology_cache = cache
        self.update(g, order=0)

    @classmethod
    def from_file(cls, file_path : str, cache : OntologyCache)->Self:
        declared_namespaces = Gerf.get_xml_namespaces(file_path)
        print(f"Declared Namespaces={declared_namespaces}")
        g = Graph()
        g.parse(file_path)
        # Find the URI of the default namespace
        try:
            default_uri = next(uri for prefix, uri in g.namespaces() if prefix == "")
            print(f"Default uri={default_uri}")
            # Find the named prefix (e.g., 'kgmod') that maps to the same URI as the default
            preferred_prefix = next((prefix for prefix, uri in declared_namespaces.items() if str(uri) == str(default_uri) and prefix != ""), None)
            print(f"Preferred Prefix={preferred_prefix}")
            # Rebind the namespace to use the named prefix
            if preferred_prefix:
                g.bind(preferred_prefix, default_uri, replace=True)

        except StopIteration:
            # There is no default uri
            pass
        return cls(g, cache)
    
    @staticmethod
    def copy_graph(original_graph):
        copy_graph = Graph(
            store=original_graph.store,
            identifier=original_graph.identifier,
            namespace_manager=original_graph.namespace_manager
            )
        for triple in original_graph:
            copy_graph.add(triple)
        return copy_graph

    @staticmethod
    def get_xml_namespaces(file_path):
        with open(file_path, 'r') as file:
            context = ET.iterparse(file, events=['start-ns'])
            # Convert list of (prefix, uri) tuples to a dictionary
            return dict([item for action, item in context])

    @staticmethod
    def get_base_uri(uri_str: str):
        # urldefrag separates the URI into (root, fragment)
        root, fragment = urldefrag(uri_str)
        # If there is a fragment, the namespace is the root + '#'
        if fragment:
            return root + "#"
        # Otherwise, the namespace is the URI up to the last '/'
        return uri_str.rsplit("/", 1)[0] + "/"

    def _get_relationship_definitions(self):
        return set([v.identifier for v in self.relations.values()])

    def _get_class_definitions(self):
        return set([c for e in self.entities.values() for c in e._observed_rdf_classes])

    def _infer_ontology_list(self):
        # Assuming types and predicates are referenced from some
        # canonical ontology, go over these objects and return a
        # list of possible candidate ontologies.
        relations = self._get_relationship_definitions()
        types = self._get_class_definitions()
        candidate_ontology_set = set(
            [Gerf.get_base_uri(c) for c in relations.union(types)]
        )
        return candidate_ontology_set

    def _update_entities_relations_from_triple(self, triple, order: int):
        s, p, o = triple
        # Process the subject - s
        if s in self.entities:
            if p in self.entities[s].interactions:

                if o not in self.entities[s].interactions[p]:
                    self.entities[s].interactions[p].add(o)
                else:
                    self.entities[s].interactions[p] = set()
                    self.entities[s].interactions[p].add(o)
            else:
                self.entities[s].interactions[p] = set()
                self.entities[s].interactions[p].add(o)
            self.entities[s]._observed_outgoing_relations.add(p)
            self.entities[s]._observed_rdf_terms.add(type(s))
        else:
            s_ent = ObservedEntity(identifier=s, order=order, gerf_object=self)
            self.entities[s] = s_ent
            self.entities[s]._observed_outgoing_relations.add(p)
            self.entities[s]._observed_rdf_terms.add(type(s))
            self.entities[s].interactions[p] = set()
            self.entities[s].interactions[p].add(o)

        # Process the object - o

        if o not in self.entities:
            o_ent = ObservedEntity(identifier=o, order=order, gerf_object=self)
            self.entities[o] = o_ent

        if p == RDF.type:
            #            self.entities[o]._observed_rdf_classes.add(RDFS.Class)
            #            self.entities[o]._observed_rdf_terms.add(type(RDFS.Class))
            self.entities[s]._observed_rdf_classes.add(o)

        if isinstance(o, Literal):
            self.entities[o]._observed_rdf_classes.add(RDFS.Literal)
            self.entities[o]._observed_rdf_terms.add(type(o))
        elif isinstance(o, (URIRef, BNode)):
            self.entities[o]._observed_rdf_terms.add(type(o))

        self.entities[o]._observed_incoming_relations.add(p)

        # Process the predicate - p
        if p in self.relations:
            if type(o) not in self.relations[p]._observed_rdf_object_terms:
                self.relations[p]._observed_rdf_subject_terms.add(type(s))
                self.relations[p]._observed_rdf_object_terms.add(type(o))
            else:
                o_rel = self.relations[p]
                self.relations[p]._observed_rdf_subject_terms.add(type(s))
                self.relations[p]._observed_rdf_object_terms.add(type(o))
        else:
            o_rel = ObservedRelationClass(identifier=p, order=order, gerf_object=self)
            self.relations[p] = o_rel
            self.relations[p]._observed_rdf_subject_terms.add(type(s))
            self.relations[p]._observed_rdf_object_terms.add(type(o))

        self.relations[p]._observed__count = self.relations[p]._observed__count + 1

    def _enrich_entities_relations_from_global(self):
        # After populating the full entities/relations information, make use
        # of the lookups to add final cross-referencing observations at
        # entity and relation level
        for identifier, entity in self.entities.items():
            entity_relations_d = self.entities[identifier].interactions
            if not isinstance(identifier, Literal):
                if RDF.type in entity_relations_d:
                    self.entities[identifier]._observed_rdf_classes = (
                        entity._observed_rdf_classes.union(entity_relations_d[RDF.type])
                    )
                    
            for relation, obj_set in entity_relations_d.items():
                self.relations[relation]._observed_rdf_subject_classes = self.relations[
                    relation
                ]._observed_rdf_subject_classes.union(entity._observed_rdf_classes)
                for obj_pointer in obj_set:
                    obj = self.entities[obj_pointer]
                    self.relations[relation]._observed_rdf_object_classes = (
                        self.relations[relation]._observed_rdf_object_classes.union(
                            obj._observed_rdf_classes
                        )
                    )


    def update_cache(self):
        cache_ontologies = set(self.ontology_cache.registry)
        start_ontology_count = len(cache_ontologies)
        inferred_required_ontologies = self._infer_ontology_list()
        # Simple placeholder - any standing aliases to be worked into the below dictionary construction
        cache_update_ontologies = {
            k: k for k in inferred_required_ontologies - cache_ontologies
        }
        self.ontology_cache.register_ontologies(cache_update_ontologies)
        end_ontology_count = len(set(self.ontology_cache.registry))
        o_diff = end_ontology_count - start_ontology_count
        if o_diff > 0:
            print(f"Added {o_diff} new ontologies")
        else:
            print("No new ontologies added.")

    def update_total_graph(self):
        self.total_graph = self.source_graph + self.ontology_graph + self.inferred_graph

    def create_ontology_graph(self):
        o_graph = Graph()
        for o in self._infer_ontology_list():
            o_file = self.ontology_cache.registry.get(o)
            if o_file is not None:
                o_graph.parse(os.path.join(self.ontology_cache.cache_directory, o_file))
        self.ontology_graph = o_graph
        
        return o_graph

    def perform_inference_closure(self):
        total_graph_copy = Graph()

        for triple in set(self.total_graph):
            total_graph_copy.add(triple)
        DeductiveClosure(RDFS_Semantics).expand(total_graph_copy)
        self.inferred_graph = self.inferred_graph + (total_graph_copy-self.total_graph)
        print(f"Inferred {len(self.inferred_graph)} new triples")
        self.update(self.inferred_graph, order=99)

    def get_entities_pending_metadata(self):
        all_classes = self._get_class_definitions()
        all_relationships = self._get_relationship_definitions()
        undef_relationships = all_relationships - set(self.entities)
        undef_classes = all_classes - set(
            [k for k, v in self.entities.items() if v.interactions != {}]
        )
        entities_pending_metadata = undef_relationships.union(undef_classes)
        return entities_pending_metadata

    def _enrich_metadata_for_entities(
        self, entity_list: set[URIRef], o_graph: Graph, order
    ):
        triple_count = 0
        for obj in entity_list:
            onto_triples = o_graph.triples((obj, None, None))
            for triple in onto_triples:
                self._update_entities_relations_from_triple(triple, order=order)
                triple_count = triple_count + 1
        if triple_count != 1:
            plural = "s"
        else:
            plural = ""
        print(f"Processed {triple_count} triple{plural}.")

    def enrich_metadata(self):
        delta = -1
        n = 0
        ents_pending_metadata = self.get_entities_pending_metadata()
        start_count = len(ents_pending_metadata)
        while delta != 0:
            n = n + 1
            print(f"Round {n}...")
            self.update_cache()
            o_graph = self.create_ontology_graph()
            self._enrich_metadata_for_entities(ents_pending_metadata, o_graph, order=n)
            ents_pending_metadata = self.get_entities_pending_metadata()
            delta = len(ents_pending_metadata) - start_count
            start_count = len(ents_pending_metadata)

    def update(self, g: Graph, order: int):

        # Populate information into the raw_graph_dict/relations/entities dictionaries
        for triple in g:
            self._update_entities_relations_from_triple(triple, order)
        self._enrich_entities_relations_from_global()


    ## Simple inference on targeted relationships - consider using RDFSClosure or OWL-RL
    # for more expressivity.

    def inference_super_class(self):
        entities=set(self.entities.keys())
        o_graph = self.create_ontology_graph()
        order=max([e.order for e in self.entities.values()])+1
        self._enrich_metadata_for_entities(entities,o_graph,order=order)
        for entity in entities:
            self._apply_super_class_assignment_for_entity(entity, order=order)

    def _get_super_classes_of_class(self, 
                                    class_entity, 
                                    super_class_set)->set:
        """Traverse the graph over RDFS.subClassOf, collecting the 
        tree of parent super-classes for this class definition"""
        if super_class_set is None:
            super_class_set=set()
        class_enitiy_object = self.entities.get(class_entity, 
                                                ObservedEntity(
                                                    identifier=None, 
                                                    order=None, gerf_object=self))
        immediate_super_classes = class_enitiy_object.interactions.get(RDFS.subClassOf, set())
        for sup in immediate_super_classes:
            super_class_set.add(sup)
            super_class_set=super_class_set.union(self._get_super_classes_of_class(sup, super_class_set))
        return super_class_set
    
    def _apply_super_class_assignment_for_entity(self, 
                                                 entity,
                                                 order:int):
        
        entity_classes = self.entities.get(entity, 
                                           ObservedEntity(
                                               identifier=None, 
                                                order=None, 
                                                gerf_object=self)
                                            ).interactions.get(RDF.type, set())
        super_class_set=set()
        for e_class in entity_classes:
            super_class_set = super_class_set.union(self._get_super_classes_of_class(e_class, None))
        
        super_class_triples=set()
        for s_class in super_class_set:
            super_class_triples.add((entity, RDF.type, s_class))
        for triple in super_class_triples:
            self._update_entities_relations_from_triple(triple=triple, order=order)