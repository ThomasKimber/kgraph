"""Utilities for performing analytics on a networkx graph"""

import networkx as nx
import numpy as np

def is_cyclic(g):
    try:
        nx.find_cycle(g)
        return True
    except nx.NetworkXNoCycle:
        return False

def classify_graph(graph):
    edge_count = len(graph.edges())
    node_degrees = {n : (graph.in_degree(n), graph.out_degree(n)) for n in graph.nodes()}
    node_count = len(node_degrees)
    graph_is_cyclic = is_cyclic(graph)
    graph_is_tree = nx.is_tree(graph)
    leaf_node_count = len([1 for d in node_degrees.values() if sum(d)==1])
    graph_has_single_hub_node = (node_count>2 and \
                                 (len([n for n,d in node_degrees.items() \
                                       if sum(d)==edge_count])==1)) or \
                                (node_count==2 and (len([n for n,d in node_degrees.items() \
                                                         if sum(d)==edge_count])==2))


    source_nodes = set([n for n,d in node_degrees.items() if d[0]==0])
    sink_nodes = set([n for n,d in node_degrees.items() if d[1]==0])

    transition_nodes = set([n for n,d in node_degrees.items() if (d[0]-d[1])==0]) # 'balanced' nodes

    return {
        "edge_count" : edge_count,
        "node_count" : node_count, 
        "graph_is_cyclic" : graph_is_cyclic, 
        "graph_is_tree" : graph_is_tree, 
        "leaf_node_count" : leaf_node_count, 
        "graph_has_single_hub_node" : graph_has_single_hub_node, 
        "source_nodes" : len(source_nodes), 
        "sink_nodes" : len(sink_nodes),
        "transition_nodes" : len(transition_nodes),
        "radius" : nx.radius(nx.to_undirected(graph))
    }

def calculate_metrics_over_induced_subgraphs(graph):
    subgraph_components = nx.weakly_connected_components(graph)
    subgraphs = sorted([(nx.subgraph(graph, c), len(c)) 
                        for c in subgraph_components], key=lambda x : x[1], 
                        reverse=True)
    sg_records=[]
    sg_nodes=[]
    for e, (sg, c) in enumerate(subgraphs):
        sg_records.append (classify_graph(sg))
        sg_nodes.append(set(sg.nodes()))
    return {"population" : len(graph), 
            "partitions" : len(subgraphs), 
            "metrics" : sg_records, 
            "subgraphs" : sg_nodes}

def summarise_metrics_records(metrics_record):
    pop=metrics_record['population']
    part=metrics_record['partitions']
    mean_p_size=np.mean([m['node_count'] for m in metrics_record['metrics']])
    mean_p_std=np.std([m['node_count'] for m in metrics_record['metrics']])
    mean_p_radius=np.mean([m['radius'] for m in metrics_record['metrics']])
    mean_source_ratio=np.mean([m['source_nodes']/m['node_count'] for m in metrics_record['metrics'] ])
    mean_sink_ratio=np.mean([m['sink_nodes']/m['node_count'] for m in metrics_record['metrics'] ])
    mean_trans_ratio=np.mean([m['transition_nodes']/m['node_count'] for m in metrics_record['metrics'] ])
    mean_leaf=np.mean([m['leaf_node_count'] for m in metrics_record['metrics']]) 
    prop_cyclic=np.mean([1 if m['graph_is_cyclic'] else 0 for m in metrics_record['metrics']])
    prop_tree=np.mean([1 if m['graph_is_tree'] else 0 for m in metrics_record['metrics']])
    prop_hub=np.mean([1 if m['graph_has_single_hub_node'] else 0 for m in metrics_record['metrics']])
    
    return {
         "population" : pop, 
         "partitions" : part, 
         "mean_p_size" : mean_p_size, 
         "mean_p_std" : mean_p_std,
         "mean_p_radius" : mean_p_radius,
         "p_cyclic" : prop_cyclic, 
         "p_tree" : prop_tree,
         "p_source" : mean_source_ratio,
         "p_sink" : mean_sink_ratio,
         "p_trans" : mean_trans_ratio,
         "p_hubs" : prop_hub
        }
