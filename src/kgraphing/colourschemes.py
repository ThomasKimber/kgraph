"""Bucket containing curated sets of colour schemes for display use"""
from itertools import cycle

colour_schemes = {"bold4" :  ["#ff3e3a", "#0496ff","#ffbc42","#17a600"],

                  "rich10" : [  "#001219", "#005f73", 
                                "#0a9396", "#94d2bd", 
                                "#e9d8a6", "#ee9b00", 
                                "#ca6702", "#bb3e03", 
                                "#ae2012", "#9b2226"],

                "spectral10" : ["#ff0000", "#ff8700", 
                                "#ffd300", "#deff0a", 
                                "#a1ff0a", "#0aff99", 
                                "#0aefff", "#147df5", 
                                "#580aff", "#be0aff"],

                "muted_rainbow10" : ["#fe4a49","#fe9158",
                                "#f4b701", "#828646",
                                "#3c905f", "#008da3",
                                "#236186", "#462255",
                                "#734785", "#9d4366"],

                "metro9" :  [   "#ea5545", "#f46a9b", 
                                "#ef9b20", "#edbf33", 
                                "#ede15b", "#bdcf32", 
                                "#87bc45", "#27aeef",
                                "#b33dc6"],

                "dutch9" :  [   "#e60049", "#ffa300", "#e6d800", 
                                "#50e991", "#00bfa0", "#b3d4ff",  "#0bb4ff", 
                                "#dc0ab4", "#9b19f5"],

                "nights9" :    ["#b30000", "#7c1158", 
                                "#4421af", "#1a53ff",
                                "#0d88e6", "#00b7c7", 
                                "#5ad45a", "#8be04e", 
                                "#ebdc78"],

                "pastels9" : [  "#fd7f6f", "#7eb0d5", 
                                "#b2e061", "#bd7ebe", 
                                "#ffb55a", "#ffee65", 
                                "#beb9db", "#fdcce5", 
                                "#8bd3c7"],

                            # bakerloo, central, circle, district
                "tfl-tube" : [ "#B26300", "#dc241f", "#ffc80a", "#007D32",
                            # hammersmity-city, jubilee, metropolitan, northern
                              "#f589a6", "#838d93", "#9b0058", "#000000",
                            # picadilly, victoria, waterloo-city
                            "#0019a8", "#039be5", "#76d0bd",
                            # bus, overground, dlr
                            "#dc241f","#fa7b05", "#00afad"
                ]

                            }

def gen_cycle(colour_scheme):
    """
    Generate a cycle of colours from the specified colour scheme.
    
    :param colour_scheme: Name of the colour scheme to use.
    :return: A cycle object that can be used to iterate through the colours.
    """
    if colour_scheme in colour_schemes:
        return cycle(colour_schemes[colour_scheme])
    raise ValueError(f"Colour scheme '{colour_scheme}' not found.")

def get_colour_scheme(colour_scheme):
    """
    Get the colour scheme as a list of colours.
    
    :param colour_scheme: Name of the colour scheme to retrieve.
    :return: A list of colours from the specified colour scheme.
    """
    if colour_scheme in colour_schemes:
        return colour_schemes[colour_scheme]
    raise ValueError(f"Colour scheme '{colour_scheme}' not found.")
