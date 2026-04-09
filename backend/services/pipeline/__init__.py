"""
miam Eat In Pipeline — Stage orchestration package.

Pipeline stages:
  1+2  query_extractor   → QueryOntology
  2b   fusion            → RetrievalContext
  3    retriever         → list[dict]  (raw recipe candidates)
  4    ranker            → list[dict]  (ranked + labelled)
  5    refinement_agent  → str         (structured context for generation)
  6    response_generator → dict       (generated_text + results)

Entry point: eat_in_pipeline.run_eat_in_pipeline()
"""
from services.pipeline.eat_in_pipeline import run_eat_in_pipeline

__all__ = ["run_eat_in_pipeline"]
