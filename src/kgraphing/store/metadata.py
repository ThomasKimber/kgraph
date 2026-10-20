"""Templating and utilities for defining a simple data-catalogue within a knowledge graph:
See: https://www.w3.org/TR/vocab-dcat/"""

from enum import Enum
from dataclasses import dataclass, asdict, field
import datetime
from rdflib import URIRef, Literal, Graph
from rdflib.namespace import RDF, RDFS, DCAT, DCTERMS


class MetaDataType(str, Enum):
    catalog = "catalog"
    dataset = "dataset"
    resource = "resource"


@dataclass
class ModifiableData:
    created: datetime.datetime = field(init=False)  # http://purl.org/dc/terms/W3CDTF
    modified: datetime.datetime = field(init=False)  # http://purl.org/dc/terms/W3CDTF

    def __setattr__(self, key, value):
        """Called when an attribute is set on the instance"""
        if hasattr(self, key):
            object.__setattr__(self, "modified", datetime.datetime.now())
        super().__setattr__(key, value)

    def __post_init__(self):
        self.created = datetime.datetime.now()
        self.modified = datetime.datetime.now()


@dataclass
class NamedGraphMetaData(ModifiableData):
    uri: URIRef  # The uri of the named graph
    title: str  # The title of the named graph
    label: str  # The label to be used for the named graph
    language: (
        str  # ISO language value - conforming to https://www.rfc-editor.org/info/bcp47
    )
    description: str  # DCTERMS.description
    metadata_type: MetaDataType
    created: datetime.datetime = field(init=False)  # http://purl.org/dc/terms/W3CDTF
    modified: datetime.datetime = field(init=False)  # http://purl.org/dc/terms/W3CDTF

    def to_graph(self):
        # Return the metadata package as an rdflib Graph object
        triple_list = []
        if self.metadata_type in [member.value for member in MetaDataType]:
            if self.metadata_type == "catalog":
                identity_triple = (self.uri, RDF.type, DCAT.Catalog)
            elif self.metadata_type == "dataset":
                identity_triple = (self.uri, RDF.type, DCAT.Dataset)
        else:
            identity_triple = (self.uri, RDF.type, DCAT.Resource)

        title_triple = (
            self.uri,
            DCTERMS.title,
            Literal(self.title, lang=self.language),
        )
        label_triple = (self.uri, RDFS.label, Literal(self.label, lang=self.language))
        description_triple = (
            self.uri,
            DCTERMS.description,
            Literal(self.description, lang=self.language),
        )
        # self.created = datetime.datetime.now()
        created_triple = (
            self.uri,
            DCTERMS.created,
            Literal(self.created.isoformat(), datatype=DCTERMS.W3CDTF),
        )
        modified_triple = (
            self.uri,
            DCTERMS.modified,
            Literal(self.modified.isoformat(), datatype=DCTERMS.W3CDTF),
        )
        triple_list.extend(
            [
                identity_triple,
                title_triple,
                label_triple,
                description_triple,
                created_triple,
                modified_triple,
            ]
        )
        g = Graph(store="Oxigraph")
        g.bind("dcterms", DCTERMS)
        g.bind("dcat", DCAT)
        print(triple_list)
        for s, p, o in triple_list:
            g.add((s, p, o))
        return g

    def graph_metrics_dict(self, data_graph: Graph) -> dict:
        total_triples = len(data_graph)
        predicates = set(data_graph.predicates())
        predicate_counts = {}
        for p in predicates:
            predicate_counts[p] = len(list(data_graph.triples((None, p, None))))
        types = set([t for _, _, t in data_graph.triples((None, RDF.type, None))])
        type_counts = {}
        for t in types:
            type_counts[t] = len(list(data_graph.triples((None, RDF.type, None))))
        typed_subjects = set(data_graph.subjects(RDF.type, None))
        all_subjects = set(data_graph.subjects())
        untyped_subjects = all_subjects - typed_subjects
        metrics_dict = {
            "triple_count": total_triples,
            "predicates": predicates,
            "predicate_count": predicate_counts,
            "types": types,
            "type_count": type_counts,
            "untyped_count": len(untyped_subjects),
        }
        return metrics_dict
