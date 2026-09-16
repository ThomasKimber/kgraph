"""Utility code for working with a knowledge graph store"""

from enum import Enum
import uuid
from urllib.parse import urljoin
from rdflib import Dataset, URIRef, BNode, Literal, Graph
from rdflib.plugins.stores import sparqlstore, memory
from rdflib.namespace import RDF


class StoreType(str, Enum):
    memory = "memory"
    jena = "jena"


class MergePolicy(str, Enum):
    FULL_REPLACE = "full_replace"
    ENTITY_REPLACE = "entity_replace"
    PROPERTY_REPLACE = "property_replace"
    UNION = "union"


DEFAULT_GRAPH_URI = "http://foo.bar/"


class KGStore:

    @staticmethod
    def _bnode_to_sparql(node):
        if isinstance(node, BNode):
            return f"<bnode:{node}>"
        return node.n3()

    def __init__(
        self,
        store_type: StoreType = StoreType.memory,
        base_graph_uri: str = DEFAULT_GRAPH_URI,
        query_url: str | None = None,
        update_url: str | None = None,
    ):
        if store_type == StoreType.memory:
            self.store = memory.Memory()
        elif store_type == StoreType.jena:
            self.store = sparqlstore.SPARQLUpdateStore(
                query_url=query_url,
                context_aware=True,
                node_to_sparql=KGStore._bnode_to_sparql,
            )
            if not any([v is None for v in [query_url, update_url]]):
                self.store.open((query_url, update_url))
            else:
                raise ValueError(
                    f"Bad parameter, both query_url and update_url need populating."
                )

        self.base_graph_uri = base_graph_uri
        self.dataset = Dataset(
            store=self.store, default_union=True, default_graph_base=self.base_graph_uri
        )

    def list_graphs(self):
        """Return a list of all named graphs in the store"""
        # Note that self.store.contexts() returns a similar list,
        # but one that might include empty graphs.
        # The sparql method returns only those graphs that contain
        # at least one triple.
        sparql_q = """SELECT distinct ?g 
        WHERE { GRAPH ?g { ?s ?p ?o. } }"""

        return [r.get("g") for r in self.dataset.query(sparql_q)]

    def drop_graph(self, named_graph: URIRef) -> None:
        drop_graph_sparql = f"DROP GRAPH {named_graph.n3()}"
        if named_graph in self.list_graphs():
            self.dataset.update(drop_graph_sparql)
            self.store.commit()
            print(f"Graph `{named_graph}` dropped from store.")
        else:
            print(f"Graph `{named_graph}` not found in store.")

    def clear_graph(self, named_graph: URIRef) -> None:
        clear_graph_sparql = f"CLEAR GRAPH {named_graph.n3()}"
        if named_graph in self.list_graphs():
            self.dataset.update(clear_graph_sparql)
            self.store.commit()
            print(f"Graph `{named_graph}` cleared from store.")
        else:
            print(f"Graph `{named_graph}` not found in store.")

    def get_graph(self, graph_id: URIRef | None = None) -> Graph:
        if graph_id is None:
            unique_id = uuid.uuid4().hex
            graph_id = URIRef(urljoin(self.base_graph_uri, unique_id))
        store_graph = self.dataset.graph(graph_id)
        return store_graph

    def save_graph(
        self,
        data_graph: Graph,
        graph_id: URIRef | None = None,
        drop_existing: bool = False,
    ) -> URIRef:
        graph = self.get_graph(graph_id)
        if drop_existing:
            self.clear_graph(URIRef(graph.identifier))
        quads = [
            (*t[0:3], graph.identifier) for t in data_graph.triples((None, None, None))
        ]
        self.dataset.addN(quads)
        self.store.commit()
        print(f"Loaded {len(quads)} to Graph `{graph.identifier.toPython()}`")
        return graph

    def update_graph(
        self,
        graph_data: Graph,
        graph_id: URIRef | None = None,
        target_graph_id: URIRef | None = None,
        scenario: MergePolicy = MergePolicy.UNION,
    ):

        if target_graph_id is None:
            target_graph = self.get_graph(graph_id)
        else:
            target_graph = self.get_graph(target_graph_id)
        base_graph = self.get_graph(graph_id)
        d, k, a = KGStore._gen_deltas(
            update_graph=graph_data, base_graph=base_graph, scenario=scenario
        )
        print(f"d:{d}")
        print(f"k:{k}")
        print(f"a:{a}")
        print(target_graph.identifier)

        try:
            for triple in d:
                target_graph.remove(triple)
            # We don't need to load these under normal circumstances
            # Commenting out for visibility
            # keep_quads = [(*t[0:3], target_graph.identifier) for t in k]
            # self.dataset.addN(keep_quads)
            add_quads = [(*t[0:3], target_graph.identifier) for t in a]
            self.dataset.addN(add_quads)
            self.store.commit()
        except Exception as e:
            self.store.rollback()
            raise e
        finally:
            target_graph.close()
        return target_graph

    def _get_predicate_counts_for_graph(self, 
                                        g: Graph):
        sparql_q = """
            SELECT ?predicate (COUNT(?subject) as ?count)
            WHERE { 
                ?subject ?predicate ?object
            }
            GROUP BY ?predicate"""
        q_results = g.query(sparql_q)
        return {k: p.toPython() for k,p in list(q_results)}

    def _get_type_counts_for_graph(self, 
                                        g: Graph):
        sparql_q = """
            SELECT ?type (COUNT(?subject) as ?count)
            WHERE { 
                ?subject <http://www.w3.org/1999/02/22-rdf-syntax-ns#type> ?type
            }
            GROUP BY ?type"""
        q_results = g.query(sparql_q)
        return {k: p.toPython() for k,p in list(q_results)}

    def get_graph_metrics(self, data_graph: Graph) -> dict:
        total_triples = len(data_graph)
        #predicates = set(data_graph.predicates()) # This call fetches everything back from the server - all s,p,o values - filtering only after collecting everything
        predicate_counts = self._get_predicate_counts_for_graph(data_graph)      
        type_counts = self._get_type_counts_for_graph(data_graph)
        typed_subjects = set(data_graph.subjects(RDF.type, None))
        all_subjects = set(data_graph.subjects())
        untyped_subjects = all_subjects - typed_subjects
        metrics_dict = {
            "triple_count": total_triples,
            "predicate_count": predicate_counts,
            "type_count": type_counts,
            "untyped_count": len(untyped_subjects),
        }
        return metrics_dict

    @staticmethod
    def _tuple_groups(tuples, bitset):
        """Apply a bitset filter to a list of equally-sized
        tuples and return the filtered contents."""
        gtuples = []
        # All tuples must be the same length:
        if len(tuples) > 0:
            bits = len(tuples[0])
            template = "{bitset:" + "0" + str(bits) + "b" + "}"

            for tups in tuples:
                gtuples.append(
                    tuple(
                        [
                            tups[e]
                            for e, b in enumerate(template.format(bitset=bitset))
                            if b != "0"
                        ]
                    )
                )
        return gtuples

    @staticmethod
    def _collect_group_tuples(tuples, bitset):
        t_groups = KGStore._tuple_groups(tuples, bitset)
        t_group_dict = dict()
        for e, g in enumerate(t_groups):
            if g not in t_group_dict.keys():
                t_group_dict[g] = []
            t_group_dict[g].append(tuples[e])
        return t_group_dict

    @staticmethod
    def _sets_to_lir(set_a, set_b):
        l, i, r = set_a - set_b, set_a.intersection(set_b), set_b - set_a
        return l, i, r

    @staticmethod
    def _gen_deltas(
        update_graph: Graph,
        base_graph: Graph,
        scenario: MergePolicy = MergePolicy.UNION,
    ) -> tuple[list, list, list]:

        existing_triples = []
        delete_triples = []
        add_triples = []

        scenario_to_bitset = {
            MergePolicy.FULL_REPLACE: 0,
            MergePolicy.ENTITY_REPLACE: 4,
            MergePolicy.PROPERTY_REPLACE: 6,
            MergePolicy.UNION: 7,
        }

        if scenario in scenario_to_bitset.keys():
            g_tuples_A = KGStore._collect_group_tuples(
                list(base_graph.triples((None, None, None))),
                scenario_to_bitset.get(scenario, 7),
            )
            g_tuples_B = KGStore._collect_group_tuples(
                list(update_graph.triples((None, None, None))),
                scenario_to_bitset.get(scenario, 7),
            )
            g_set_A = set(g_tuples_A.keys())
            g_set_B = set(g_tuples_B.keys())
            L, I, R = KGStore._sets_to_lir(g_set_A, g_set_B)
            #print(len(L), len(I), len(R))

            # Keep all triples from L - no action if using old_graph
            for key in L:
                for t in g_tuples_B.get(key, []):
                    existing_triples.append(t)
            # Add all triples in R
            for key in R:
                for t in g_tuples_B.get(key, []):
                    add_triples.append(t)
            # From I, delete any triples from B and insert any triples from A
            # If a full s,p,o triple exists in both sets, then add it to the
            # existing list
            for key in I:
                for t in g_tuples_A.get(key, []):
                    if t not in g_tuples_B.get(key, []):
                        delete_triples.append(t)
                    else:
                        existing_triples.append(t)
                for t in g_tuples_B.get(key, []):
                    if t not in g_tuples_A.get(key, []):
                        add_triples.append(t)
                    else:
                        existing_triples.append(t)
            # Options at this point are:
            #   1) Create a brand-new graph that's the result of the merge
            #       Create new graph and
            #       + add_triples and
            #       + existing_triples
            #   2) Mutate the existing graph
            #       - delete_triples and
            #       + add_triples (some of may already exist if I contained duplicates, but it's fine)

        else:
            raise ValueError(f"Scenario value {scenario} not in range {{1,2,3,4}}")
        return (delete_triples, existing_triples, add_triples)
