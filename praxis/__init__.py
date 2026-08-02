"""Praxis construction core — the Python side that builds tutorials for a subject.

The seed library's modules (curriculum, scaffold_notebooks, nbstatus) stay top-level;
this package holds the new subject-agnostic machinery, starting with the BYO-key LLM
client the curriculum generator and scaffolder call into.
"""
