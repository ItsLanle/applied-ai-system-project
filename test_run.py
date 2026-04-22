from bughound_agent import BugHoundAgent
from llm_client import MockClient

# Test heuristic mode (passing None to force heuristics)
agent = BugHoundAgent(None)
code = '''def load_text_file(path):
    try:
        f = open(path, "r")
        data = f.read()
        f.close()
    except:
        return None

    return data'''

result = agent.run(code)
print('Heuristic mode:')
print('Issues:', result['issues'])
print('Fixed code:')
print(result['fixed_code'])
print('Risk:', result['risk'])