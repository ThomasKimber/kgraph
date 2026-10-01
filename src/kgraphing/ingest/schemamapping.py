"""This module provides the SchemaMapping class which is used
to decode a schemamapping.json configuration file and create
an object which (via the .to_rdf_graph() method), provided a
dataframe, will return an rdflib.Graph object reflecting the
result of the mappings.
"""

# General Imports
from itertools import product
from datetime import datetime
import uuid
import re
import urllib.parse
import json
import jsonschema, jsonschema.exceptions
from rdflib import Graph as rdflibGraph, Namespace, URIRef, Literal, BNode
from rdflib.namespace import RDF, RDFS, OWL
from rdflib.collection import Collection
import numpy as np
import pandas as pd

# Local package imports
from kgraphing.declarations import RDFTriple, SCHEMAMAPPINGSCHEMA, KGNAM


def split_on_comma_respecting_quotes(some_string):
    """A crude delimiter parser using comma as delimiter,
    respects common quote-masking."""
    quote_respecter = re.compile(r"(?<!\\)(\".+?(?<!\\)\")")
    in_d = {}
    text = "".join(list(some_string))
    fms = quote_respecter.findall(text)
    for m in fms:
        key = uuid.uuid4().hex
        in_d[key] = m
        text = text.replace(m, key)
    values = []
    for value in text.split(","):
        if any((k in value for k in in_d.keys())):
            for k, v in in_d.items():
                if k in value:
                    values.append(value.replace(k, v).strip())
        else:
            values.append(value.strip())
    return values


def retrieve_fqn_parent(fqn):
    """Return the parental portion from a provided fqn string"""
    return ".".join(fqn.split(".")[:-1])


def collate_fqn_parents(fqn: str) -> list[str]:
    """Return all the ancestors referenced in an fqn string"""
    stub = fqn
    parents = []
    while len(stub.split(".")) > 1:
        parent = retrieve_fqn_parent(stub)
        parents.append(parent)
        stub = parent
    return parents


class SchemaMapping:
    """A SchemaMapping is a collection of individual column->rdf data
    mappings which defines how data in a tabular format should be
    consumed to create an rdf graph. The configuration used to
    define a given schema-mapping is provided at instantiation
    via a suitably formatted json file."""

    schema = SCHEMAMAPPINGSCHEMA
    # Assign the namespace "DATA" to be used for temporary in-memory raw data graph
    DATA = Namespace("http://data#")

    def __init__(self, config_filename):
        """Read in a configuration file, validate it and generate a
        well-populated SchemaMapping object"""

        with open(config_filename, "r") as jsonfile:
            self.config = json.load(jsonfile)
        try:
            jsonschema.validate(self.config, schema=SchemaMapping.schema)
        except jsonschema.exceptions.ValidationError as err:
            print(err)

        # Note that this forces any NamedObject Instances to mirror their associated
        # SubjectTag column-names
        # A discrepancy between these two would cause the lineage to break.
        self.specifications = {}
        self.fully_qualified_names_tree = {}
        self.glob_vars = {}
        for varname, varvalue in self.config["GlobalVariables"].items():
            self.glob_vars[varname] = varvalue

        self.stats_dict = {}

        # Validate that no InstanceNames appear more than once!
        # Duplicate InstanceNames in the mapping cause problems!

        for named_object_definition in self.config["NamedObjects"]:
            for instance in named_object_definition["Instances"]:
                iname = instance.get("InstanceName")
                targetclass = named_object_definition.get("TargetClass")
                classbase = URIRef(named_object_definition["URIBase"])
                named_instance = NamedObjectInstanceSpecification(
                    self, targetclass, classbase, instance
                )
                self.specifications[iname] = named_instance
                if (
                    named_instance._subject__column
                    not in self.fully_qualified_names_tree.keys()
                ):
                    self.fully_qualified_names_tree[named_instance._subject__column] = (
                        named_instance._parent__column
                    )

        for relationship_definition in self.config["Relationships"]:
            for instance in relationship_definition["Instances"]:
                iname = instance.get("InstanceName")
                targetclass = relationship_definition.get("Predicate")
                relation_instance = RelationshipInstanceSpecification(
                    self, targetclass, instance
                )
                self.specifications[iname] = relation_instance

        for property_definition in self.config["Properties"]:
            for instance in property_definition["Instances"]:
                iname = instance.get("InstanceName")
                targetclass = property_definition.get("Predicate")
                property_instance = PropertyInstanceSpecification(
                    self, targetclass, instance
                )
                self.specifications[iname] = property_instance

        # Update the list of object instances with the naming_hierarchy_path used later
        # to establish its FQN
        referenced_columns = []
        for iname, instance_object in self.specifications.items():
            if isinstance(instance_object, NamedObjectInstanceSpecification):
                instance_object._populate_naming_hierarchy_path()
            referenced_columns.extend(
                [c for c in instance_object.column_list if c != "<root>"]
            )

        self.referenced_columns = list(set(referenced_columns))
        multivalue_columns = []
        for c in self.referenced_columns:
            for instance in self.specifications.values():
                if c == instance._expose_multi_value_field():
                    multivalue_columns.append(c)
        self.multivalue_columns = list(set(multivalue_columns))

    def traverse_hierarchy_path(self, start, acc=None):
        """Given a dictionary containing node-to-node parental linkages {child:parent}
        and a start node,
        traverse the hierarchy and return the path taken from start node, all the way
        up the tree, until it reaches the (local) top."""
        if acc is None:
            acc = [start]
        next_value = self.fully_qualified_names_tree.get(start)
        if next_value is not None:
            acc.append(next_value)
            self.traverse_hierarchy_path(next_value, acc)
        return acc

    def populate_entity_fqn_index(self, raw_graph):
        """Create set of entities from the raw graph"""
        entities = []
        defined_entities = set()
        entity_fqn_index = {}
        for datarow in [
            r[0] for r in raw_graph.triples((None, RDF.type, SchemaMapping.DATA["row"]))
        ]:
            for spec in [
                s
                for s in self.specifications.values()
                if isinstance(s, NamedObjectInstanceSpecification)
            ]:
                # print("\t", s._instance_name)
                # print("\t", s.column_list)
                # print("\t subcol:", s._subject__column)
                # print("\t parcol:", s._parent__column)
                # print("\t muvals:", s._multivalues)
                for newobj in spec.NamedObjectListFromDataGraphRow(datarow, raw_graph):

                    if newobj.fully_qualified_name not in entity_fqn_index.keys():
                        if spec._is_definition:
                            defined_entities.add(newobj)

                        entities.append(newobj)
                        entity_fqn_index[newobj.fully_qualified_name] = newobj
                    else:
                        # Already found this one - but does the saved object need
                        # replacing with one sourced as a definition?

                        if (
                            not entity_fqn_index[
                                newobj.fully_qualified_name
                            ].is_definition
                            and newobj.is_definition
                        ):
                            entities.remove(
                                entity_fqn_index[newobj.fully_qualified_name]
                            )
                            entity_fqn_index[newobj.fully_qualified_name] = newobj
                            entities.append(newobj)
                            entity_fqn_index[newobj.fully_qualified_name] = newobj
        # Save the entity_fqn_index to be accessible at object level
        self.entities = entities
        self.defined_entities = defined_entities
        print("Defined, References")
        print(
            len(self.defined_entities), len(set(self.entities) - self.defined_entities)
        )
        self.stats_dict["defined_entities_count"] = len(self.defined_entities)
        self.stats_dict["all_entities_count"] = len(set(self.entities))
        self.stats_dict["undefined_entities_count"] = len(
            set(self.entities) - self.defined_entities
        )
        self.entity_fqn_index = entity_fqn_index

    def to_rdf_graph(self, dataframe) -> rdflibGraph:
        """Convert the dataframe into a raw graph where rows are "triplified" with
        minimal steer from the SchemaMapping.
        This raw graph is expressed in the raw data namespace and consists of rows with
        floating column(name) predicates linking to properties in the dataframe."""
        print(f"rdf_parse:start {datetime.now()}")
        raw_graph = self._rdflib_graph_from_dataframe(dataframe)
        self.populate_entity_fqn_index(raw_graph)
        triple_generating_objects = list(self.entity_fqn_index.values())

        # Here there's an opportunity to review the formation of the triple_generating_objects
        # To determine whether all/any namespace hierarchies are fully populated.
        # i.e. That if a namespace is inferred anywhere in any of the FullyQualifiedNames used to
        # describe the objects being referenced, then there ought to be full and complete
        # pathway from each leaf object, all the way up the tree.
        raw_fqn_parents = {
            q
            for n in triple_generating_objects
            for q in collate_fqn_parents(n.fully_qualified_name)
        }
        nameless_parents = [
            p for p in raw_fqn_parents if p not in self.entity_fqn_index.keys()
        ]
        print(
            f"Warning - the following FullyQualifiedNames are inferred "
            + f"but not directly referenced in this file: {nameless_parents}"
        )

        for fqn, o in self.entity_fqn_index.items():
            # For each object, create a link to the isScopedWithin object that acts as its parent
            o_parent = self.entity_fqn_index.get(o.parent_fqn, None)
            if o_parent is not None:
                scope_r = RelationObject(o, o_parent, KGNAM.isScopedWithin)
                triple_generating_objects.extend([scope_r])
            else:
                print(
                    f"Warning, object {fqn} unable to connect to its "
                    + f"parent {o.parent_fqn} - doesn't exist in file"
                )

       
        # Once the entities are defined, next it's time to link them all via the various
        # relationship linkages
        for datarow in [
            r[0] for r in raw_graph.triples((None, RDF.type, SchemaMapping.DATA["row"]))
        ]:
            for s in list(self.specifications.values()):
                if isinstance(s, RelationshipInstanceSpecification):
                    triple_generating_objects.extend(
                        s.constructRelationFromDataGraphRow(
                            datarow, raw_graph, self.entity_fqn_index
                        )
                    )
                elif isinstance(s, PropertyInstanceSpecification):
                    triple_generating_objects.extend(
                        s.constructPropertyFromDataGraphRow(
                            datarow, raw_graph, self.entity_fqn_index
                        )
                    )

        collection_assignments_triples = []
        for datarow in [
                    r[0] for r in raw_graph.triples((None, RDF.type, SchemaMapping.DATA["row"]))
                ]:
            for s in [s for s in self.specifications.values() if s._is_list and isinstance(s, NamedObjectInstanceSpecification)]:
                new_collection_triples = s.listAssignmentTriples(
                                    datarow,
                                    raw_graph,
                                    self.entity_fqn_index)
                collection_assignments_triples.extend (new_collection_triples)

        print("Objects, Unique Objects")
        print(len(triple_generating_objects), len(set(triple_generating_objects)))

        return_graph = rdflibGraph(bind_namespaces="rdflib")

        ns_d = self.config.get("Namespaces", {})
        for ns_prefix, nsuri in ns_d.items():
            return_graph.bind(ns_prefix, nsuri)

        for e in triple_generating_objects:
            for t in e.to_triples():
                return_graph.add(t)

        print(f"There are {len(collection_assignments_triples)} in the collection_assignments_triples")
        for t in collection_assignments_triples:
            return_graph.add(t)

        print(f"rdf_parse:end {datetime.now()}")

        # Any validation ought to be performed at this stage:

        return return_graph

    def _rdflib_graph_from_dataframe(self, dataframe) -> rdflibGraph:
        """Reads in a dataframe and converts it into an anonymous graph"""
        g = rdflibGraph(bind_namespaces="rdflib")
        g.bind("DATA", SchemaMapping.DATA)
        g.add((SchemaMapping.DATA.row, RDF.type, OWL.Class))
        g.add((SchemaMapping.DATA.row, RDFS.label, Literal("Row")))

        for c in dataframe.columns:
            url_c = urllib.parse.quote(c)
            g.add(
                (SchemaMapping.DATA[f"column({url_c})"], RDF.type, OWL.DatatypeProperty)
            )  # Define the column as a datatype property
            g.add(
                (SchemaMapping.DATA[f"column({url_c})"], RDFS.label, Literal(c))
            )  # Attach a simple label to the datatype property
            g.add(
                (
                    SchemaMapping.DATA.row,
                    SchemaMapping.DATA.has_field,
                    SchemaMapping.DATA[f"column({url_c})"],
                )
            )

        for c in self.glob_vars.keys():
            url_c = urllib.parse.quote(c)
            g.add(
                (SchemaMapping.DATA[f"column({url_c})"], RDF.type, OWL.DatatypeProperty)
            )  # Define the column as a datatype property
            g.add(
                (SchemaMapping.DATA[f"column({url_c})"], RDFS.label, Literal(c))
            )  # Attach a simple label to the datatype property
            g.add(
                (
                    SchemaMapping.DATA.row,
                    SchemaMapping.DATA.has_field,
                    SchemaMapping.DATA[f"column({url_c})"],
                )
            )

        unspecified_colums = set()
        for row_i, data in dataframe.replace(
            {np.nan: None, pd.NaT: None, pd.NA: None, "": None}
        ).iterrows():
            row_url = SchemaMapping.DATA[uuid.uuid4().hex]
            row_index = Literal(row_i)
            g.add((row_url, RDF.type, SchemaMapping.DATA.row))
            g.add((row_url, SchemaMapping.DATA.row_ident, row_index))

            # Populate the contents of `GlobalVariables` as pseudo-columns associated with each
            # data row
            for c, v in self.glob_vars.items():
                url_c = urllib.parse.quote(c)
                p_url = SchemaMapping.DATA[f"column({url_c})"]
                o_literal = Literal(v)
                g.add((row_url, p_url, o_literal))

            for c in dataframe.columns:

                url_c = urllib.parse.quote(c)
                p_url = SchemaMapping.DATA[f"column({url_c})"]

                if data[c] is not None and not pd.isna(data[c]):
                    # print(c, ":", data[c])
                    raw_data_value = data[c]
                    if c in self.referenced_columns:
                        # The column is identified as being referenced
                        # Now we need to see if it needs interpreting as a multivalue column or not
                        # N.B. there could be some discrepancy - i.e. one specification might
                        # interpret the value as multi-value, while another one doesn't.
                        # Let's adopt the convention that if *any* specification imposes the
                        # multivalues flag, then *all* specifications must treat it as such.
                        if c in self.multivalue_columns:
                            # Apply explosion transformation on the value presented
                            try:
                                data_fetched = split_on_comma_respecting_quotes(
                                    raw_data_value
                                )
                            except Exception as e:
                                print(
                                    f"`{e}`",
                                    c,
                                    raw_data_value,
                                )
                                raise e

                        else:
                            data_fetched = [raw_data_value]
                    else:
                        data_fetched = [raw_data_value]
                        # print(f"This column {c} isn't referenced in the spec!")
                        unspecified_colums.add(c)

                    for v in data_fetched:
                        # For every value in the data_fetched list, add the data to the graph via the appropriate column
                        o_literal = Literal(v)
                        g.add((row_url, p_url, o_literal))

                    # Where the column is defined as a multivalue_column, there's an option for preserving the 
                    # # fetched data as a list - we encode this into an rdflist of literal contents accessible
                    # via the key original_columname__listhead - which we'll make use of later in the process:
                    if c in self.multivalue_columns:
                        head_node = BNode() # create a new BNode to act as the head
                        Collection(g, 
                                   head_node, 
                                   [Literal(v) for v in data_fetched])
                        # Join the subject-row to the created list head as a subtype of the column
                        l_url = SchemaMapping.DATA[f"column({url_c}__listhead)"]
                        g.add((row_url, l_url, head_node))



        print(f"The following columns are not listed in the spec {unspecified_colums}")
        return g


class SchemaMappingInstanceSpecification:
    """A SchemaMappingInstanceSpecification is the root class for
    NamedObjectInstanceSpecification, RelationshipInstanceSpecification
    and PropertyInstanceSpecification classes.
    Each class reflects the different expectations for mappings depending
    on the mapping type."""

    def __init__(self, parent):
        self.parent_SchemaMapping = parent
        self.column_list = []
        self._multivalues = None
        self._is_list = None
        self._list_elements_specification = None

    @staticmethod
    def extract_valid_fqns(rowurl, data_graph, fetch_key):
        """Expand the fetch_key specification to list all
        possible index values"""
        f_key = [f for f in fetch_key if f != "<root>"]
        raw_fqn = SchemaMappingInstanceSpecification.get_keylist_from_datarow(
            rowurl, data_graph, f_key
        )
        # Each block of the fqn could contain multiple values - we need to build the collection
        # of fqns that could possibly be constructed from each combination -  it's the
        # cartesian product that we're looking for.

        results = []
        if len(raw_fqn) > 0 and raw_fqn[0] != []:
            for fqn_spec in list(product(*raw_fqn)):
                results.append(
                    ".".join([n.toPython() for n in fqn_spec[::-1] if n != []])
                )
            return results
        else:

            return []

    @staticmethod
    def get_keylist_from_datarow(rowurl, data_graph, spec):
        """Given a specification, extract all matching keylist
        information from the provided data_graph"""
        fetched_values = []
        for fetch_key in spec:
            fetched_key_values = (
                SchemaMappingInstanceSpecification.get_values_from_datarow(
                    rowurl, data_graph, fetch_key
                )
            )
            fetched_values.append([fkv for fkv in fetched_key_values if fkv != []])
        return fetched_values

    @staticmethod
    def get_values_from_datarow(rowurl, data_graph, key):
        """Given a row url and predicate key, return all the values that match."""
        data_key = URIRef(SchemaMapping.DATA[f"column({key})"])
        key_values = [r[2] for r in data_graph.triples((rowurl, data_key, None))]
        return key_values

    def _populate_column_list(self):
        """Extract column names from class and assign
        to self.column_list"""
        for attr_name, attr_value in vars(self).items():
            if attr_name.endswith("__column"):
                self.column_list.append(attr_value)

    def _expose_multi_value_field(self):
        """Some fields in the mapping specification can have their
        multivalue set. Where this is true, the appropriate field
        on which multivalues are defined is returned - if this is
        not, then the function returns None."""
        if self._multivalues:
            if isinstance(self, NamedObjectInstanceSpecification):
                return self._subject__column
            elif isinstance(self, RelationshipInstanceSpecification):
                return self._object__column
            elif isinstance(self, PropertyInstanceSpecification):
                return self._literal__column
            else:
                raise TypeError(
                    f"Class {self.__class__.__name__} not recognised as one \
                        supporting this function."
                )
        else:
            return None


class NamedObject:
    """A NamedObject encapsulates the output of applying a NamedObjectInstanceSpecification
    extraction against a given row of data"""

    def __init__(
        self, type_uris, fully_qualified_name, names, namespace, is_definition: bool
    ):
        ENT = Namespace(namespace)
        self.uri = ENT[f"{uuid.uuid4().hex}"].toPython()
        self.types = []
        self.names = names
        self.fully_qualified_name = fully_qualified_name
        self.parent_fqn = retrieve_fqn_parent(fully_qualified_name)
        self.is_definition = is_definition
        # Coerce self.type to be a string
        for uri in type_uris:
            if isinstance(uri, str):
                self.types.append(uri)
            elif isinstance(uri, URIRef):
                self.types.append(uri.toPython())

    def to_triples(self) -> list[RDFTriple]:
        """Return the contents of the object as a suitable collection of rdf triples"""
        triples = []
        for t in self.types:
            triples.append((URIRef(self.uri), RDF.type, URIRef(t)))

        for n in self.names:
            if "." not in n:
                triples.append(
                    (
                        URIRef(self.uri),
                        URIRef(KGNAM.Name),
                        Literal(n),
                    )
                )

        triples.append(
            (
                URIRef(self.uri),
                URIRef(KGNAM.FullyQualifiedName),
                Literal(self.fully_qualified_name),
            )
        )
        return triples

    def __repr__(self):
        return (
            f"<NamedObject:{self.types[0]}//{self.fully_qualified_name}>({self.uri})>"
        )


class NamedObjectInstanceSpecification(SchemaMappingInstanceSpecification):
    """A NamedObjectInstanceSpecification defines, for a given mapping,
    what information should be extracted from a data row in order to
    generate a NamedObject"""

    def __init__(self, parent, target_class, classbase, instance_d):
        """Extract the values hosted in the configuration and store as
        object properties"""
        super().__init__(parent)
        self.target_class = target_class
        self._instance_name = instance_d["InstanceName"]
        self._subject__column = instance_d["SubjectTag"]
        self._parent__column = instance_d["ParentTag"]
        if "Definition" in instance_d.keys():
            self._is_definition = instance_d["Definition"]
        else:
            self._is_definition = False
        self._classbase_uri = classbase
        if 'ListContent' in instance_d.keys():
            self._is_list = True
            self._list_elements_specification = instance_d['ListContent']
        else:
            self._is_list = False
            self._list_elements_specification = None

        if self._parent__column is None or str(self._parent__column).strip() == "":
            print(f"setting <root> for {self._instance_name}")
            self._parent__column = "<root>"
        else:
            print(f"_parent_column for {self._instance_name} is {self._parent__column}")
        self._multivalues = instance_d.get("EnableMultiValues", False)

        super()._populate_column_list()

    def __repr__(self):
        return f"<{self.__class__.__name__}:{self._instance_name}\
            /{self._parent__column}/{self._subject__column}>"

    def _populate_naming_hierarchy_path(self):
        """Internal function to perform a hierarchy_path traversal
        the outcome of which is stored in self.naming_hierarchy_path"""
        if isinstance(self, NamedObjectInstanceSpecification):
            # Needs parent column to determine naming_hierarchy - only works for NamedObjects
            self.naming_hierarchy_path = (
                self.parent_SchemaMapping.traverse_hierarchy_path(self._subject__column)
            )
        else:
            raise TypeError(
                "This function can only be called on InstanceSpecifications \
                    that reference a parent"
            )



    def listAssignmentTriples(
        self, row_uri, data_graph, entity_fqn_index
    ) -> list[RDFTriple]:
        """Where a NamedObject specification uses the _is_list and 
        _list_elements_specification properties - we must extract those
        values from the source raw graph and return them as a set of triples
        assigned to the list-head.
        """
        assignment_triples = []

        element_spec = self.parent_SchemaMapping.specifications.get(self._list_elements_specification, None)
        if element_spec is None:
            return assignment_triples

        raw_list_heads = [o for s,p,o in data_graph.triples((row_uri, SchemaMapping.DATA[f"column({element_spec._subject__column}__listhead)"], None))]

        # Get the list possible objects for which we want to do some list assignment: 

        assignment_heads = []

        for n in SchemaMappingInstanceSpecification.extract_valid_fqns(
            row_uri, data_graph, self.naming_hierarchy_path
            ) :
            assignment_heads.append(entity_fqn_index.get(n))

        
        for ass_head in assignment_heads:
            for raw_head in raw_list_heads:
                list_items = Collection(data_graph, raw_head)
                fqn_roots = self.extract_valid_fqns(
                    row_uri, 
                    data_graph, 
                    self.parent_SchemaMapping.traverse_hierarchy_path(element_spec._subject__column)[1:]
                )
                cobject_names = list()
                for root in fqn_roots:
                    for li in list_items:
                        cobject_names.append(".".join([root, li]))
                object_list = [URIRef(entity_fqn_index.get(n).uri)
                            for n in cobject_names 
                            if entity_fqn_index.get(n) is not None]

                temp_g = rdflibGraph()
                list_triples = Collection(temp_g, 
                                        URIRef(ass_head.uri), 
                                        object_list).graph.triples((None, None, None))
                
                assignment_triples.extend(list_triples)
        return assignment_triples






    
    def NamedObjectListFromDataGraphRow(self, row_uri, data_graph) -> list[NamedObject]:
        """For a given row_uri, using the data_graph, extract a list
        of NamedObjects per the NamedObjectListFromDataGraphRow specification
        A NamedObject must have one or more principle:
              types
              names (KGNAM)
              labels (KGNAM) (not necessarily true)
              namespace
              FullyQualifiedNames (KGNAM)
        In addition, it might have any additional, overlapping properties that describe the
        object, but for basic construction, we start with this list to populate the minimal,
        KGNAM based content (...or do we??)"""

        type_uris = [URIRef(self.target_class)]

        fqns = SchemaMappingInstanceSpecification.extract_valid_fqns(
            row_uri, data_graph, self.naming_hierarchy_path
        )
        # What instances exist that contain name values?
        # Let's use the final value from each fqn as a proxy for Name
        namespace = self._classbase_uri
        object_list = []
        if fqns is not None:
            for fqn in fqns:
                names = [fqn.split(".")[-1]]
                if fqn is not None:
                    object_list.append(
                        NamedObject(
                            type_uris, fqn, names, namespace, self._is_definition
                        )
                    )
        return object_list


class RelationObject:
    """A RelationObject defines the expected data values (and utility methods)
    to be extracted by applying a RelationshipInstanceSpecification against
    a data-row"""

    def __init__(self, subject: NamedObject, object: NamedObject, relation_uri: str):
        self.subject = subject
        self.object = object
        self.relation_uri = relation_uri

    def to_triples(self) -> list[RDFTriple]:
        """Return the contents of the object as a suitable collection of rdf triples"""
        triples = []

        triples.append(
            (
                URIRef(self.subject.uri),
                URIRef(self.relation_uri),
                URIRef(self.object.uri),
            )
        )

        return triples

    def __repr__(self):
        return (
            f"<Relation:{self.relation_uri}//<({self.subject.uri}-{self.object.uri})>"
        )


class RelationshipInstanceSpecification(SchemaMappingInstanceSpecification):
    """A RelationshipInstanceSpecification defines, for a given mapping,
    what information should be extracted from a data row in order to
    generate a RelationObject"""

    def __init__(self, parent, target_class, instance_d):
        """Extract the values hosted in the configuration and store as
        object properties"""
        super().__init__(parent)
        self.target_class = target_class
        self._instance_name = instance_d["InstanceName"]
        self._subject__column = instance_d["SubjectTag"]
        self._object__column = instance_d["ObjectTag"]
        self._multivalues = instance_d.get("EnableMultiValues", False)
        super()._populate_column_list()

    def __repr__(self):
        return f"<{self.__class__.__name__}:{self._instance_name}\
            /{self._object__column}/{self._subject__column}>"

    def constructRelationFromDataGraphRow(
        self, row_uri, data_graph, entity_fqn_index
    ) -> list[RelationObject]:
        """For a given row_uri, using the data_graph, extract all
        RelationObject per the RelationshipInstanceSpecification specification"""

        # Collect the set of candidate fqn specifications (i.e. the columns used to fetch the
        # FQNs from the data row) for both sides of the relationship (subject, object)
        # These are expressed as lists containing string values that describe the original
        # column names
        candidate_subject_spec = self.parent_SchemaMapping.traverse_hierarchy_path(
            self._subject__column
        )
        candidate_object_spec = self.parent_SchemaMapping.traverse_hierarchy_path(
            self._object__column
        )

        # Get the FQNs from the data row - but these can be tricky in that if no match for
        # the root of the FQN is found,
        # it still shows, but with element[0] being empty
        subject_fqns = SchemaMappingInstanceSpecification.extract_valid_fqns(
            row_uri, data_graph, candidate_subject_spec
        )
        object_fqns = SchemaMappingInstanceSpecification.extract_valid_fqns(
            row_uri, data_graph, candidate_object_spec
        )
        subject_entities = []
        if subject_fqns is not None:
            for fqn in subject_fqns:
                subject_entities.append(entity_fqn_index.get(fqn, None))

        object_entities = []
        if object_fqns is not None:
            for fqn in object_fqns:
                object_match = entity_fqn_index.get(fqn, None)
                if object_match is None:
                    print(f"\t\tObject match not found for {fqn}")
                object_entities.append(object_match)

        # Review the returned object lists and make a call on whether there's enough information
        # to accept
        # whatever matches are returned
        # Since the subjects and objects might be in n>1 collections, we generate the product of
        # both to
        # create a single relations which consists of all combinations of both (in practice,
        # subjects should)
        # be singular, but the multivalues option means objects can contain multiple
        # possibilities
        relations = list(product(*[subject_entities, object_entities]))
        relation_list = []
        
        for relation in relations:
            if all((v is not None for v in relation)):
                sobj, oobj = relation
                relation_list.append(RelationObject(sobj, oobj, self.target_class))
        
        return relation_list


class PropertyObject:
    """A PropertyObject defines the expected data values (and utility methods)
    to be extracted by applying a PropertyInstanceSpecification against
    a data-row"""

    def __init__(self, subject: NamedObject, property_value, relation_uri: str):
        self.subject = subject
        self.property = property_value
        self.relation_uri = relation_uri

    def to_triples(self) -> list[RDFTriple]:
        """Return the contents of the object as a suitable collection of rdf triples"""
        triples = []

        triples.append(
            (
                URIRef(self.subject.uri),
                URIRef(self.relation_uri),
                Literal(self.property),
            )
        )

        return triples

    def __repr__(self):
        return f"<Relation:{self.relation_uri}//<({self.subject.uri}-{self.property})>"


class PropertyInstanceSpecification(SchemaMappingInstanceSpecification):
    """A PropertyInstanceSpecification defines, for a given mapping,
    what information should be extracted from a data row in order to
    generate a PropertyObject"""

    def __init__(self, parent, target_class, instance_d):
        """Extract the values hosted in the configuration and store as
        object properties"""
        super().__init__(parent)
        self.target_class = target_class
        self._instance_name = instance_d["InstanceName"]
        self._subject__column = instance_d["SubjectTag"]
        self._literal__column = instance_d["LiteralTag"]
        self._multivalues = instance_d.get("EnableMultiValues", False)
        super()._populate_column_list()

    def constructPropertyFromDataGraphRow(
        self, row_uri, data_graph, entity_fqn_index
    ) -> list[PropertyObject]:
        """For a given row_uri, using the data_graph, extract all
        PropertyObjects per the PropertyInstanceSpecification specification"""
        # Get the subject fqn
        candidate_subject_spec = self.parent_SchemaMapping.traverse_hierarchy_path(
            self._subject__column
        )
        # How many fqns are possible here?
        print(f"specs-count:{len(candidate_subject_spec)}, spec: {candidate_subject_spec}")

        # Get the FQNs from the data row - but these can be tricky in that if no match for the
        # root of the FQN is found,
        # it still shows, but with element[0] being empty
        subject_fqns = SchemaMappingInstanceSpecification.extract_valid_fqns(
            row_uri, data_graph, candidate_subject_spec
        )
        subject_entities = []
        if subject_fqns is not None:
            for fqn in subject_fqns:
                subject_entities.append(entity_fqn_index.get(fqn, None))

        # Now extract the literal contents from the data row, which should *already* respect
        # earlier multi-values processing
        literal_values = SchemaMappingInstanceSpecification.get_values_from_datarow(
            row_uri, data_graph, self._literal__column
        )

        # Review the returned object lists and make a call on whether there's enough information
        # to accept
        # whatever matches are returned
        # Since the subjects and objects might be in n>1 collections, we generate the product of
        # both to
        # create a single relations which consists of all combinations of both (in practice,
        # subjects should)
        # be singular, but the multivalues option means objects can contain multiple
        # possibilities
        relations = list(product(*[subject_entities, literal_values]))
        relation_list = []
        
        for relation in relations:
            if all((v is not None for v in relation)):
                sobj, oobj = relation
                relation_list.append(PropertyObject(sobj, oobj, self.target_class))
        
        return relation_list

    def __repr__(self):
        return f"<{self.__class__.__name__}:{self._instance_name}\
            /{self._literal__column}/{self._subject__column}>"
