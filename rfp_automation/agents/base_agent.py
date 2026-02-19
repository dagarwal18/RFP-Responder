from abc import ABC, abstractmethod
from rfp_automation.models.state import RFPState

class BaseAgent(ABC):
    def __init__(self, name: str):
        self.name = name

    @abstractmethod
    async def run(self, state: RFPState) -> RFPState:
        pass
