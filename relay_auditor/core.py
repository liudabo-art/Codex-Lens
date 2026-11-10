"""Public Python API. Desktop/CLI use this owner of the same controller and store."""
from .controller import Service
from .storage import Store
from .profiles import Profiles
from .transport import APIClient

API_VERSION=2


class Auditor:
    def __init__(self,directory,*,persist_settings=False,vault=None,client_factory=APIClient):
        self.store=Store(directory)
        try:
            profiles=Profiles(self.store.directory/'private',vault=vault) if persist_settings else None
            self.service=Service(self.store,client_factory=client_factory,profiles=profiles)
        except Exception:
            self.store.close(); raise
        self.closed=False

    def __enter__(self): return self
    def __exit__(self,*args): self.close()

    def configure(self,*args,**kwargs): return self.service.configure(*args,**kwargs)
    def estimate(self,*args,**kwargs): return self.service.estimate(*args,**kwargs)
    def run(self,*args,**kwargs): return self.service.run(*args,**kwargs)
    def submit(self,*args,**kwargs): return self.service.submit(*args,**kwargs)
    def cancel(self,job_id=None): return self.service.cancel(job_id)
    def snapshot(self): return self.service.snapshot()
    def usage_snapshot(self): return self.service.usage_snapshot()

    def close(self):
        if self.closed: return
        self.closed=True; self.service.stop()
        with self.service.lock:
            if not self.service.busy: self.store.close()
            else: self.service.on_idle=self.store.close


__all__=['Auditor','API_VERSION']
