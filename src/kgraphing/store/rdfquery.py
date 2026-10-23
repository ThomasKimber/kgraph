"""Utility code for registering, and calling prepared SPARQL
queries on an rdflib bound graph."""
from typing import Optional, Self, Any
from rdflib.plugins.sparql import prepareQuery
from rdflib import Graph, URIRef, Literal, BNode
from rdflib.query import Result

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
                 ):
        if init_namespace is None:
            self.prepared_query=prepareQuery(query)
        else:
            self.prepared_query=prepareQuery(query, initNs=init_namespace)
        self.parameters = parameters
        self.name = name
        self.description = description

    def validate_bindings(self,
                          parameter_bindings : dict[str,Any]) -> tuple[bool,list[str]]:
        # Perform type-checking of parameter_bindings against declared parameter specs
        errors=[]
        for p,b in parameter_bindings.items():
            if p not in self.parameters.keys():
                errors.append(f"Parameter {p} not declared as a valid parameter.")
            elif not isinstance(b, self.parameters[p]):
                errors.append(f"Parameter {p} value ({str(b)}) of type {type(b)} doesn't match declared parameter type {self.parameters[p]}.")
        if len(errors)>0:
            return False, errors
        return True, errors

    def execute(self,
            graph : Graph,
            parameter_bindings : dict[str,Any])-> Result:
        results=graph.query(self.prepared_query, initBindings=parameter_bindings)
        return results
