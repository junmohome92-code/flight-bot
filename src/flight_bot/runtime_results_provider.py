from __future__ import annotations

from .providers import GoogleFlightsPlaywrightProvider


class RuntimeGoogleResultsProvider(GoogleFlightsPlaywrightProvider):
    """Production identity for the canonical accepted Google-results provider.

    All behavior now lives in ``GoogleFlightsPlaywrightProvider`` so Windows
    acceptance, manual notification tests, scheduled searches and Ubuntu/Docker
    cannot silently drift into separate Cheapest/query implementations again.
    """

    name = "google-playwright-results-observed-accepted-flow"
    accepted_for_alerts = True
