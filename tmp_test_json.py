import re
import json

raw_json = '''{
  "content": "## Technical Solution
  
Some text here with newlines.

More text.
",
  "requirements_addressed": ["REQ-0001", "REQ-0002"],
  "word_count": 50
}'''

def parse_llm_json(text):
    text = text.strip()
    try:
        data = json.loads(text, strict=False)
        return data.get("content", ""), data.get("requirements_addressed", [])
    except json.JSONDecodeError:
        pass
        
    print("Fallback regex parsing...")
    content = ""
    reqs = []
    
    # Try to extract content string
    # We look for "content": followed by optional whitespace and a quote, 
    # then anything up to the next ", followed by "requirements_addressed" or "word_count" or }
    content_match = re.search(r'"content"\s*:\s*"(.*?)"\s*(?:,\s*"requirements_addressed"|,\s*"word_count"|\})', text, re.DOTALL)
    if content_match:
        content = content_match.group(1)
        # unescape escaped quotes if any
        content = content.replace('\\"', '"')
    
    # Try to extract requirements
    req_match = re.search(r'"requirements_addressed"\s*:\s*\[(.*?)\]', text, re.DOTALL)
    if req_match:
        req_str = req_match.group(1)
        reqs = re.findall(r'"([^"]+)"', req_str)
        
    return content, reqs

print(parse_llm_json(raw_json))
