"""Spatial package -- bundled China geospatial data layers and query engine.

Usage:
    from geocorpus_builder.spatial import SpatialQueryEngine, LayerRegistry

    engine = SpatialQueryEngine()
    result = engine.locate(116.4, 39.9)  # → {"cn_provinces": {"name_zh": "北京市", ...}}
"""

from .engine import SpatialQueryEngine
from .registry import LayerRegistry, LayerMeta
from .relations import SpatialRelations
from .importer import import_shapefile, import_directory

__all__ = ["SpatialQueryEngine", "LayerRegistry", "LayerMeta",
           "SpatialRelations", "import_shapefile", "import_directory"]
