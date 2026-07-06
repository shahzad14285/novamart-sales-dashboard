"""Service-layer package for the NovaMart Sales Intelligence Dashboard.

``services/`` sits alongside ``utils/`` (framework-agnostic business
calculations) and ``components/``/``pages/`` (Streamlit UI) as a home
for cross-cutting application services -- functionality that isn't a
business calculation and isn't UI rendering, such as converting data
into export formats. Future services (reporting, PDF generation, AI
recommendations) are expected to live here as their own modules, each
with a single, narrow responsibility.
"""
