"""String enums for all constrained fields defined in geocorpus_schema.json."""

from enum import Enum


class TextType(str, Enum):
    DEFINITION = "definition"
    METHOD = "method"
    RESULT = "result"
    RESULT_TEMPLATE = "result_template"
    CAPTION = "caption"
    QA_ANSWER = "qa_answer"
    INTERPRETATION = "interpretation"


class Domain(str, Enum):
    CRYOSPHERE = "cryosphere"
    HYDROLOGY = "hydrology"
    METEOROLOGY = "meteorology"
    CLIMATOLOGY = "climatology"
    GEOMORPHOLOGY = "geomorphology"
    ECOSYSTEM = "ecosystem"
    HUMAN_ACTIVITY = "human_activity"
    HAZARD_RISK = "hazard_risk"
    GENERAL_GEOGRAPHY = "general_geography"
    GEOSPATIAL_DATA = "geospatial_data"
    STATISTICS = "statistics"
    CORPUS = "corpus"
    GEOSPATIAL_RELATION = "geospatial_relation"


class GeoObjectType(str, Enum):
    GLACIER = "glacier"
    GRID = "grid"
    REGION = "region"
    STATION = "station"
    BASIN = "basin"
    EVENT = "event"
    RASTER_LAYER = "raster_layer"
    GLACIER_AND_GRID = "glacier_and_grid"


class SpatialScale(str, Enum):
    OBJECT = "object"
    GRID = "grid"
    REGION = "region"
    NATIONAL = "national"
    MULTI_SCALE = "multi_scale"
    GRID_OR_GLACIER = "grid_or_glacier"
    OBJECT_GRID = "object_grid"
    WITHIN_OBJECT = "within_object"
    OBJECT_PAIR = "object_pair"
    OBJECT_GRID_PAIR = "object_grid_pair"
    OBJECT_OR_REGION = "object_or_region"
    SCHEMA = "schema"


class ClaimType(str, Enum):
    DESCRIPTIVE = "descriptive"
    COMPARATIVE = "comparative"
    CAUSAL = "causal"
    METHODOLOGICAL = "methodological"
    UNCERTAINTY = "uncertainty"
    DEFINITION = "definition"


class Confidence(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    LOW_UNTIL_REPLACED = "low_until_replaced"


class EvidenceType(str, Enum):
    STATISTIC = "statistic"
    RASTER = "raster"
    VECTOR = "vector"
    CROSSWALK = "crosswalk"
    METHOD = "method"
    FIGURE = "figure"
    LITERATURE = "literature"
    SCHEMA = "schema"


class DataType(str, Enum):
    GEO_OBJECT = "GeoObject"
    GEO_FIELD = "GeoField"
    GEO_REGION = "GeoRegion"
    GEO_EVENT = "GeoEvent"
    GEO_RELATION = "GeoRelation"
    INDICATOR = "indicator"
    DERIVED_INDICATOR = "derived_indicator"


class AggregationRule(str, Enum):
    MEAN = "mean"
    SUM = "sum"
    AREA_WEIGHTED_MEAN = "area_weighted_mean"
    MAJORITY = "majority"
    MAX = "max"
    PERCENTILE = "percentile"
    NOT_AGGREGATED = "not_aggregated"
    DERIVED = "derived"
    WEIGHT = "weight"


class Statistic(str, Enum):
    MEAN = "mean"
    MEDIAN = "median"
    TREND = "trend"
    P10 = "p10"
    P90 = "p90"
    CV = "cv"
    AREA = "area"
    COUNT = "count"
    STD = "std"
    DEFINITION = "definition"
    MEAN_CHANGE = "mean_change"
