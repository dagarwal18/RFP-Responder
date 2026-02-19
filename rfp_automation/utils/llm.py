from rfp_automation.config import settings
from groq import Groq

class LLMClient:
    def __init__(self):
        self.api_key = settings.GROQ_API_KEY
        self.model = settings.GROQ_MODEL
        if not self.api_key:
            raise ValueError("GROQ_API_KEY environment variable not set")
        
        self.client = Groq(api_key=self.api_key)

    def generate(self, system_prompt: str, user_prompt: str, temperature: float = 0.7) -> str:
        try:
            completion = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=temperature,
                max_tokens=4096,
                top_p=1,
                stop=None,
                stream=False
            )
            return completion.choices[0].message.content
        except Exception as e:
            print(f"LLM Generation Error: {e}")
            return f"Error generating response: {e}"

llm_client = LLMClient()
