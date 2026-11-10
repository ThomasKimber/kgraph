"""Utility code for registering, and calling prepared SPARQL
queries on an rdflib bound graph."""
from typing import Optional, Self, Any
from collections.abc import Iterable, Iterator
import re
from rdflib.plugins.sparql import prepareQuery
from rdflib import Graph, URIRef, Literal, BNode
from rdflib.query import Result


BATCH_START = "# @BATCH({variable})"
BATCH_VALUES = "# @BATCH_VALUES({variable})"
BATCH_END = "# @END_BATCH({variable})"

_IRI_PATTERN = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*:[^\s<>\"{}|^`\\]+$")


def safe_value(value):
    if value is None:
        return None
    if isinstance(value, (URIRef, Literal, BNode)):
        return value.toPython()

def results_to_resultlist(results):
    result_list=[]
    if results.type == 'SELECT':
        for result in results:
            result_list.append({str(c):safe_value(result[e]) for e,c in enumerate(results.vars)})
        return result_list
    elif results.type == 'CONSTRUCT':
        for result in results.graph.triples((None, None, None)):
            result_list.append({"s" : result[0], "p" : result[1], "o" : result[2]})
        return result_list

class QueryAPI:
    def __init__(self,
                 name : str,
                 query : str,
                 description : str,
                 parameters : dict[str,type],
                 init_namespace : Optional[dict[str,str]] = None,
                 batch_parameter: Optional[str] = None,
                 batch_size: int = 250,
                 ):
        self.query_template = query
        
        if init_namespace is None:
            self.prepared_query=prepareQuery(query)
        else:
            self.prepared_query=prepareQuery(query, initNs=init_namespace)
        self.parameters = parameters
        self.init_namespace = init_namespace
        self.name = name
        self.description = description

        self.batch_parameter = batch_parameter
        self.batch_size = batch_size

        if batch_parameter is not None:
            if batch_parameter not in parameters:
                raise ValueError(
                    f"Batch parameter {batch_parameter!r} must be declared "
                    "in parameters"
                )

    def validate_bindings(self,
                          parameter_bindings : dict[str,Any]) -> tuple[bool,list[str]]:
        # Perform type-checking of parameter_bindings against declared parameter specs
        errors=[]
        for p,b in parameter_bindings.items():
            if p not in self.parameters.keys():
                errors.append(f"Parameter {p} not declared as a valid parameter.")
                continue
            expected_type = self.parameters[p]
            if not isinstance(b, self.parameters[p]):
                errors.append(
                    f"Parameter {p} value ({str(b)}) of type "
                    f"{type(b).__name__} doesn't match declared parameter "
                    f"type {expected_type}.")
        return not errors, errors

    def execute(self,
            graph : Graph,
            parameter_bindings : dict[str,Any])-> Result:
        results=graph.query(self.prepared_query, initBindings=parameter_bindings)
        return results

    def execute_batched(
        self,
        graph: Graph,
        parameter_bindings: dict[str, Any],
    ) -> Iterator[Result]:
        """Execute a query with one collection-valued parameter.

        The collection is split into batches. Each batch is substituted into
        the query's `# @BATCH(parameter)` block as a SPARQL VALUES clause.
        """
        if self.batch_parameter is None:
            raise ValueError(
                f"Query {self.name!r} does not declare a batch parameter"
            )

        parameter = self.batch_parameter

        if parameter not in parameter_bindings:
            raise ValueError(
                f"Batch parameter {parameter!r} was not supplied"
            )

        values = list(parameter_bindings[parameter])

        if not values:
            return

        for start in range(0, len(values), self.batch_size):
            batch = values[start : start + self.batch_size]

            sparql = self._render_batched_query(
                parameter=parameter,
                values=batch,
            )

            prepared_query = (
                prepareQuery(sparql)
                if self.init_namespace is None
                else prepareQuery(sparql, initNs=self.init_namespace)
            )

            yield graph.query(prepared_query)

    def _render_batched_query(
        self,
        parameter: str,
        values: list[Any],
    ) -> str:
        start_marker = BATCH_START.format(variable=parameter)
        end_marker = BATCH_END.format(variable=parameter)

        start_index = self.query_template.find(start_marker)
        end_index = self.query_template.find(end_marker)

        if start_index == -1 or end_index == -1:
            raise ValueError(
                f"Query {self.name!r} must contain both {start_marker!r} "
                f"and {end_marker!r}"
            )

        end_index += len(end_marker)

        replacement = self._format_values_clause(
            parameter=parameter,
            values=values,
        )

        return (
            self.query_template[:start_index]
            + replacement
            + self.query_template[end_index:]
        )

    @staticmethod
    def _format_values_clause(
        parameter: str,
        values: list[Any],
    ) -> str:
        formatted_values = []

        for value in values:
            if isinstance(value, URIRef):
                iri = str(value)
            elif isinstance(value, str):
                iri = value
            else:
                raise TypeError(
                    f"Batch values for {parameter!r} must be URIRef or str; "
                    f"got {type(value).__name__}"
                )

            if not _IRI_PATTERN.fullmatch(iri):
                raise ValueError(
                    f"Value {iri!r} is not a safe absolute IRI for SPARQL"
                )

            formatted_values.append(f"        <{iri}>")

        if not formatted_values:
            raise ValueError("Cannot execute a batch query with no values")

        return (
            f"VALUES ?{parameter} {{\n"
            + "\n".join(formatted_values)
            + "\n}"
        )