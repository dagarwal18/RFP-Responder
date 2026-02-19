class LangGraphStateMachine:
    def __init__(self):
        self.state = {}

    def transition(self, name: str, payload: dict):
        self.state[name] = payload
