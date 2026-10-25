"""Utility functions used for decorating networkx graphs"""

from functools import partial, wraps
from typing import Any, Hashable, TypeAlias, Union
import inspect
from collections.abc import Callable

import networkx as nx

NXGraph: TypeAlias = Union[nx.Graph, nx.DiGraph, nx.MultiGraph, nx.MultiDiGraph]


def validate_unbound_function_sig(v_func, ubound_parms):
    # Perform check for node_decorator_f signature
    f_sig = inspect.signature(v_func)
    if not all(
        [
            n in ubound_parms
            for n, p in f_sig.parameters.items()
            if p.default == inspect.Parameter.empty
        ]
    ):
        raise TypeError(
            f"{v_func.func.__name__} doesn't have a valid unbound call signature {str([n
                for n,p in
                f_sig.parameters.items()
                if p.default == inspect.Parameter.empty
            ])} != {str(ubound_parms)}"
        )

    return True


def decorator_function_template(
    id: Hashable,
    data: dict[str, Any],
    classification_function: Callable,
    classification_mapping: dict[str|frozenset, dict[str, Any]],
) -> dict[str, Any]:
    key = classification_function(id, data)
    mapping = classification_mapping.get(key, {})
    return mapping


def decorate_networkx_nodes_with_function(
    nx_g: NXGraph,
    classification_function: Callable,
    classification_mapping: dict[str|frozenset, dict[str, Any]],
) -> NXGraph:
    """Given a function whose parameters accept a node name, and a dictionary of attributes,
    and whose return type is a dict, cycle over the available nodes in the graph
    and apply the updated values returned from the function onto the various nodes."""

    assert validate_unbound_function_sig(classification_function, ("id", "data"))

    dfunc = partial(
        decorator_function_template,
        classification_function=classification_function,
        classification_mapping=classification_mapping,
    )

    #    if not all([n in ('node','data') for n in f_sig.parameters.keys() ]):
    #        raise TypeError(f"{node_decorator_f} doesn't have a valid call signature (node, data)")

    for n, d in nx_g.nodes(data=True):
        dec_dict = dfunc(n, d)
        for k, v in dec_dict.items():
            nx_g.nodes[n][k] = v
    return nx_g


def decorate_networkx_edges_with_function(
    nx_g: NXGraph,
    classification_function: Callable,
    classification_mapping: dict[str|frozenset, dict[str, Any]],
) -> NXGraph:
    """Given a function whose parameters accept an edge name, and a dictionary of attributes,
    and whose return type is a dict, cycle over the available nodes in the graph
    and apply the updated values returned from the function onto the various nodes."""

    assert validate_unbound_function_sig(classification_function, ("id", "data"))

    # N.B. Note the difference in edge calling strategies between the Multi-and-Simple
    # versions of nx_g.edges - the multi-edge 'keys' flag returns an additional edge-id
    # that's used to uniquely identify edges where start, finish (s,f) isn't a strong
    # enough unique key

    dfunc = partial(
        decorator_function_template,
        classification_function=classification_function,
        classification_mapping=classification_mapping,
    )

    if isinstance(nx_g, (nx.MultiDiGraph, nx.MultiGraph)):
        for s, f, e, d in nx_g.edges(keys=True, data=True):
            dec_dict = dfunc(id=(s, f, e), data=d)
            for k, v in dec_dict.items():
                nx_g[s][f][e][k] = v
    elif isinstance(nx_g, (nx.DiGraph, nx.Graph)):
        for s, f, d in nx_g.edges(data=True):
            dec_dict = dfunc(id=(s, f), data=d)
            for k, v in dec_dict.items():
                nx_g[s][f][k] = v
    return nx_g


def get_attribute(id: Hashable, data: dict[str, Any], attribute: str) -> Any:
    """This is a template function for use with the feature decorator
    The expected inputs must include a networkx graph node,
    and associated data dictionary
    And it should be geared to outputting some classifying value
    that can be stored in the keys of a lookup styling dictionary"""
    if attribute in data.keys():
        return data[attribute]
    else:
        return "Unknown"


def apply(id: Hashable, data: dict[str, Any], func: Callable) -> Hashable:

    return func(id, data)
