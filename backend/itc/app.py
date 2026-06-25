"""
Application factory.

Wires concrete implementations to their abstract interfaces so the rest of
the codebase depends only on abstractions (dependency-injection pattern).

Usage
-----
::

    from itc.app import create_app
    gateway = create_app()["llm_gateway"]
"""

from __future__ import annotations

from typing import TypedDict

from itc.intelligence.gateway import AbstractLLMGateway, StubLLMGateway


class AppContainer(TypedDict):
    llm_gateway: AbstractLLMGateway


def create_app() -> AppContainer:
    """
    Bootstrap the application and return a container of bound services.

    Swap ``StubLLMGateway`` for the real implementation here when M1 is ready.
    """
    return AppContainer(
        llm_gateway=StubLLMGateway(),
    )
