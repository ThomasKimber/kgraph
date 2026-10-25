from typing import Optional, Self
import os
from pathlib import Path, PosixPath
import uuid
import json
from send2trash import send2trash
from rdflib.parser import Parser
from rdflib.plugin import register, PluginException
from rdflib.exceptions import ParserError
from rdflib import Graph
from urllib.parse import urlparse
from urllib.error import HTTPError, URLError
from importlib.resources import files
import shutil

from kgraphing.ontologies import core



#from rdflibowlparser import owlxml
#
#register(
#    "owl",  # Format string to use in parse()
#    Parser,
#    "rdflibowlparser.owlxml",
#    "OWLXMLParser",
#)

def is_remote_url(input_string):
    parsed = urlparse(input_string)
    # Remote URLs have schemes like 'http', 'https', 'ftp'
    return parsed.scheme in ('http', 'https', 'ftp', 's3', 'gs')

class OntologyCache:
    registry: dict[str, str]

    def __init__(self, cache_directory: str):
        self.cache_directory = Path(cache_directory).resolve()
        if not os.path.isdir(cache_directory):
            os.makedirs(cache_directory)
        self.registry = dict()
        ocache_json_filename = os.path.join(cache_directory, "ocache.json")
        self.cache_json = ocache_json_filename
        if os.path.isfile(self.cache_json):
            self.read_init()
        else:
            self.commit()

    def cleanup(self):
        """Remove all content from the cache that's not present in the registry
        Actions taken:
            keys with no associated file (missing list) are deleted from the registry
            orphan files with no registry key are deleted from the cache"""
        valid, missing, orphan = self.cross_check_registry_cache()
        pre_clean_registry_items = self.registry.copy().items()
        for m in missing:
            for k, v in pre_clean_registry_items:
                if v == m:
                    del self.registry[k]

        for o in orphan:
            send2trash(os.path.join(self.cache_directory, o))
        self.commit()

    def purge(self):
        """Completely wipe any content from the cache and reset it to clean state"""
        self.registry = {}
        self.commit()
        self.cleanup()

    def initialise(self):
        """Populate the registry with the curated collection of "core" ontologies"""
        curated_cache_json_resource = files(core).joinpath("ocache.json")
        curated_ontologies = json.loads(curated_cache_json_resource.read_text(encoding="utf-8"))
        for namespace, file_pointer in curated_ontologies.items():
            source_file = str(files(core).joinpath(file_pointer))
            self.register(namespace, True, source_file)

    def read_init(self):
        """Load the contents of the cache registry file into memory"""
        with open(self.cache_json, "r") as ocache_json_file:
            self.registry = json.load(ocache_json_file)

    def commit(self):
        with open(self.cache_json, "w") as ocache_json_file:
            json.dump(self.registry, ocache_json_file, indent=4)

    def cross_check_registry_cache(self):
        """Check integrity of registry and files
        outputs a tuple containing (valid, missing, orphan) where:
            valid is a list of valid files in the cache, for which the registry has keys
            missing is a list of keys in the registry for which there is no matching file in the cache
            orphan is a list of files in the cache for which there are no registry keys
        """
        cache_files = set()
        cache_registry_entries = set(self.registry.values())
        files = [
            f
            for f in os.listdir(self.cache_directory)
            if os.path.isfile(os.path.join(self.cache_directory, f))
        ]
        for f in files:
            if f != "ocache.json":
                cache_files.add(f)
        valid_values = cache_registry_entries.intersection(cache_files)
        unresolved_registry_entries = cache_registry_entries - cache_files
        orphan_cache_files = cache_files - cache_registry_entries
        return valid_values, unresolved_registry_entries, orphan_cache_files

    def register_ontologies(
        self, ontology_urls: dict[str, str], overwrite: bool = False
    ):
        for k, v in ontology_urls.items():
            self.register(ontology_url=k, overwrite=overwrite, alias=v)

    def register(
        self,
        ontology_url: str,
        overwrite: bool = False,
        alias: Optional[str] = None,
    ):
        o_graph = Graph(store="Oxigraph")
        if alias is not None:
            ontology_location = alias
        else:
            ontology_location = ontology_url
        if overwrite or ontology_url not in self.registry:
            try:
                o_graph.parse(ontology_location)

                if overwrite and ontology_url in self.registry:
                    serial_filename = self.registry[ontology_url]
                else:
                    if alias is None or (not isinstance(alias, (Path, PosixPath)) and is_remote_url(alias)):
                        # Where an ontology is looked up online, it should be serialised, but
                        # it's tricky to crib a proper filename from any given url, so generate
                        # a uuid-based filename that we can be fairly confident is unique. 
                        # Later curation can be used to name/manage/administer a more formally
                        # arranged set of ontologies
                        serial_filename = f"{uuid.uuid4().hex.upper()[:8]}.owl"
                    else:
                        # Currently this assumes the alias is a local file - perhaps located somewhere else
                        # on the filesystem - take the stem so that it can be converted to a .owl after
                        # serialization by rdflib.
                        # The registered version of the ontology will be this post-parsed rdflib serialisation
                        # version. 
                        # It's possible that for namespace_url_x, someone provides an alias namespace_url_y
                        # in which case, we might want to revert to the uuid-based filename generation - but
                        # for the moment, all aliasing is performed where someone has, or provides a local
                        # file-based copy of some ontology - e.g. perhaps where one is locally authored as a 
                        # file, but contains some URI that's yet to be registered with a DNR
                        filename_part = Path(alias).stem
                        serial_filename = f"{filename_part}.owl"
                serial_path = os.path.join(self.cache_directory, serial_filename)
                o_graph.serialize(serial_path, format="xml")
                self.registry[ontology_url] = serial_filename
                self.commit()
            except HTTPError as e:
                print(f"HTTPError found when processing {ontology_url}: {e}")
            except URLError as e:
                print(f"URLError found when processing {ontology_url}: {e}")
            except ParserError as e:
                print(
                    f"Parser error encountered while processing {ontology_url} - consider manually registering an alias"
                )
            except PluginException as e:
                print(
                    f"{e} encountered while processing {ontology_url} - consider manually registering an alias"
                )
            except FileNotFoundError as e:
                print(e)
            except Exception as e:
                raise e
                print(
                    f"Unable to register {ontology_url} (@{ontology_location}) due to {e}"
                )
        else:
            print(f"{ontology_url} already present in registry")
