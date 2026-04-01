"""Base tool interface for Null Realm agents."""

from abc import ABC, abstractmethod


class BaseTool(ABC):
    name: str
    description: str

    @abstractmethod
    async def execute(self, **kwargs) -> str:
        ...
