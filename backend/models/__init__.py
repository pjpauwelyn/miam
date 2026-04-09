# Personal Ontology
from .personal_ontology import (
    UserProfile,
    DietaryProfile,
    DietaryRestriction,
    CuisineAffinityProfile,
    CuisineAffinity,
    FlavorProfile,
    TextureProfile,
    CookingContext,
    KitchenEquipment,
    BudgetProfile,
    DiningVibeProfile,
    VibeAffinity,
    AdventurousnessProfile,
    NutritionalProfile,
    SocialProfile,
    LifestyleProfile,
    LocationProfile,
    ProfileTension,
    DimensionMeta,
    # Enums
    DimensionWeight,
    UpdateSource,
    CookingSkill,
    KitchenSetup,
    NutritionalAwarenessLevel,
    SocialContext,
    InspirationStyle,
    PreferenceLevel,
    TensionSeverity,
)

# Query Ontology
from .query_ontology import (
    QueryOntology,
    QueryAttribute,
    LogicalRelationship,
    QueryProfileConflict,
    EatInAttributes,
    EatOutAttributes,
    SessionContext,
    # Enums
    QueryMode,
    ValueType,
    RelationshipType,
    ConflictType,
    ConflictResolution,
)

# Fused Ontology / Retrieval Context
from .fused_ontology import RetrievalContext

# Documents
from .recipe import (
    RecipeDocument,
    RecipeIngredient,
    RecipeSubstitution,
    RecipeStep,
    DietaryFlags,
    NutritionPerServing,
)
from .restaurant import (
    RestaurantDocument,
    RestaurantCoordinates,
    RestaurantCuisineTags,
    RestaurantOpeningHours,
    RestaurantMenuItem,
    RestaurantDietaryOptions,
    RestaurantDataQualityFlags,
)

# Feedback
from .feedback import FeedbackEvent

# Session
from .session import Session, Message


__all__ = [
    # Personal Ontology models
    "UserProfile",
    "DietaryProfile",
    "DietaryRestriction",
    "CuisineAffinityProfile",
    "CuisineAffinity",
    "FlavorProfile",
    "TextureProfile",
    "CookingContext",
    "KitchenEquipment",
    "BudgetProfile",
    "DiningVibeProfile",
    "VibeAffinity",
    "AdventurousnessProfile",
    "NutritionalProfile",
    "SocialProfile",
    "LifestyleProfile",
    "LocationProfile",
    "ProfileTension",
    "DimensionMeta",
    # Personal Ontology enums
    "DimensionWeight",
    "UpdateSource",
    "CookingSkill",
    "KitchenSetup",
    "NutritionalAwarenessLevel",
    "SocialContext",
    "InspirationStyle",
    "PreferenceLevel",
    "TensionSeverity",
    # Query Ontology models
    "QueryOntology",
    "QueryAttribute",
    "LogicalRelationship",
    "QueryProfileConflict",
    "EatInAttributes",
    "EatOutAttributes",
    "SessionContext",
    # Query Ontology enums
    "QueryMode",
    "ValueType",
    "RelationshipType",
    "ConflictType",
    "ConflictResolution",
    # Fused Ontology
    "RetrievalContext",
    # Documents
    "RecipeDocument",
    "RecipeIngredient",
    "RecipeSubstitution",
    "RecipeStep",
    "DietaryFlags",
    "NutritionPerServing",
    "RestaurantDocument",
    "RestaurantCoordinates",
    "RestaurantCuisineTags",
    "RestaurantOpeningHours",
    "RestaurantMenuItem",
    "RestaurantDietaryOptions",
    "RestaurantDataQualityFlags",
    # Feedback
    "FeedbackEvent",
    # Session
    "Session",
    "Message",
]
