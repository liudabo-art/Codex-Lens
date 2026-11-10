"""Offline, deterministic synthetic demonstration. Never constructs APIClient."""
import json
from .transport import Completion

class DemoClient:
    def __init__(self,target): self.target=target
    def complete(self,case):
        # Deliberately weak demo target for a visible quality comparison.
        answer=None if self.target.model=='demo-weak' and case.seed%3==0 else case.expected
        return Completion(json.dumps({'answer':answer}),{'input_tokens':20,'output_tokens':10,'total_tokens':30})
    def list_models(self): return ['demo-reference','demo-weak']

def snapshot(directory):
    from .core import Auditor
    with Auditor(directory,client_factory=DemoClient) as core:
        for model in ('demo-reference','demo-weak'):
            alias=core.configure('https://synthetic.invalid/v1','synthetic-demo',model)
            core.run(alias,'quality',samples=10,seed=42)
        return {'demonstration':True,'warning':'Synthetic oracle outputs, not model measurements','assessment':core.snapshot()}
