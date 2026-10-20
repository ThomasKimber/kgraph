"""This module defines shared definitions and reference resources
to be imported by other modules within the package"""

import os
from importlib import resources
from typing import Tuple, TypeAlias, Union
import json
from rdflib import URIRef, Literal, BNode
from rdflib import Graph as rdflibGraph
from rdflib.namespace import Namespace

from kgraphing import shapes, ontologies
import kgraphing.jschema

# SCHEMAMAPPINGSCHEMA is the json-schema that validates schema mapping
# configuration files
with resources.as_file(
    resources.files(kgraphing.jschema) / os.path.normpath("schemamappingschema.json")
) as schema_mapping_schema_file:
    with schema_mapping_schema_file.open(
        "r", encoding="utf-8", errors="strict"
    ) as schema_mapping_schema:
        SCHEMAMAPPINGSCHEMA = json.load(schema_mapping_schema)

# KGNAM is the fixed namespace used by the kgraph suite of utilities
# Here the namespace is defined, and the underlying ontology resource
# is openend as an rdflib-Graph object, to which are bound core ontology
# namespaces to the graph's namespace manager.
KGNAM = Namespace("https://kgraph.foo/onto/kgnam#")
KGNAM_G = rdflibGraph(store="Oxigraph")

with resources.as_file(
    resources.files(ontologies) / os.path.normpath("kgnam.owl")
) as kgnam_owl:
    KGNAM_G.parse(kgnam_owl, format="xml")
    KGNAM_G.bind("KGNAM", KGNAM.title.toPython())

KGNAM_SHAPES_G = rdflibGraph(store="Oxigraph")
with resources.as_file(
    resources.files(shapes) / os.path.normpath("kgnam_shacl.ttl")
) as kgnam_shapes:
    KGNAM_SHAPES_G.parse(kgnam_shapes, format="ttl")
    KGNAM_SHAPES_G.bind("KGNAM", KGNAM.title.toPython())

# Define the type-aliases used to handle triple contents
RDFSubjectAtom: TypeAlias = Union[URIRef, BNode]
RDFPredicateAtom: TypeAlias = URIRef
RDFObjectAtom: TypeAlias = Union[URIRef, BNode, Literal]
RDFTriple: TypeAlias = Tuple[RDFSubjectAtom, RDFPredicateAtom, RDFObjectAtom]
RDFQuad: TypeAlias = Tuple[URIRef, RDFSubjectAtom, RDFPredicateAtom, RDFObjectAtom]
