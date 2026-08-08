# this is rules/app.py
"""
Application factory.

Wires concrete implementations to their abstract interfaces so the rest of
the codebase depends only on abstractions (dependency-injection pattern).

Usage
-----
::

    from itc.app import create_app
    container = create_app()
    gateway = container["llm_gateway"]
"""

from __future__ import annotations

from typing import TypedDict

from itc.core.logging import configure_logging
from itc.intelligence.gateway import AbstractLLMGateway, StubLLMGateway


class AppContainer(TypedDict):
    llm_gateway: AbstractLLMGateway


def create_app(log_level: str = "INFO") -> AppContainer:
    """
    Bootstrap the application and return a container of bound services.

    Parameters
    ----------
    log_level:
        Root logging level.  Pass ``"DEBUG"`` to enable redaction of
        GSTINs and amounts in log output.  Defaults to ``"INFO"``.

    Swap ``StubLLMGateway`` for the real implementation here when M1 is ready.
    """
    configure_logging(level=log_level)

    return AppContainer(
        llm_gateway=StubLLMGateway(),
    )
