"""Exact owned Windows Credential Manager item; no enumeration or plaintext fallback."""
import json
import os
import re

MAX_BLOB_BYTES=5*512
SECRET_FIELDS = frozenset(('relay', 'reference', 'legacy_reference_wire', 'official_reference', 'official_preset'))


def owned_id(value):
    if not isinstance(value,str) or not re.fullmatch(r'[a-f0-9]{32}',value): raise ValueError('invalid_profile_id')
    return 'RelayAuditor/v1/'+value


class UnavailableVault:
    available=False
    def read(self,profile_id):
        owned_id(profile_id)
        return None
    def write(self,profile_id,secrets):
        owned_id(profile_id)
        raise ValueError('vault_unavailable')
    def delete(self,profile_id):
        owned_id(profile_id)


class WindowsVault(UnavailableVault):
    @property
    def available(self): return os.name=='nt'

    @staticmethod
    def _api():
        import ctypes
        from ctypes import wintypes as w
        class Credential(ctypes.Structure):
            _fields_=[('Flags',w.DWORD),('Type',w.DWORD),('TargetName',w.LPWSTR),('Comment',w.LPWSTR),
                      ('LastWritten',w.FILETIME),('CredentialBlobSize',w.DWORD),('CredentialBlob',ctypes.POINTER(ctypes.c_ubyte)),
                      ('Persist',w.DWORD),('AttributeCount',w.DWORD),('Attributes',ctypes.c_void_p),
                      ('TargetAlias',w.LPWSTR),('UserName',w.LPWSTR)]
        api=ctypes.WinDLL('advapi32',use_last_error=True)
        api.CredReadW.argtypes=[w.LPCWSTR,w.DWORD,w.DWORD,ctypes.POINTER(ctypes.POINTER(Credential))]
        api.CredReadW.restype=w.BOOL
        api.CredWriteW.argtypes=[ctypes.POINTER(Credential),w.DWORD]; api.CredWriteW.restype=w.BOOL
        api.CredDeleteW.argtypes=[w.LPCWSTR,w.DWORD,w.DWORD]; api.CredDeleteW.restype=w.BOOL
        api.CredFree.argtypes=[ctypes.c_void_p]
        return ctypes,Credential,api

    def read(self,profile_id):
        name=owned_id(profile_id)
        if not self.available: return None
        ctypes,Credential,api=self._api(); pointer=ctypes.POINTER(Credential)()
        if not api.CredReadW(name,1,0,ctypes.byref(pointer)):
            if ctypes.get_last_error()==1168: return None
            raise ValueError('vault_unavailable')
        try:
            size=pointer.contents.CredentialBlobSize
            if size>MAX_BLOB_BYTES: raise ValueError('vault_unavailable')
            data=json.loads(ctypes.string_at(pointer.contents.CredentialBlob,size).decode('utf-8'))
            if not isinstance(data,dict) or any(k not in SECRET_FIELDS or not isinstance(v,str) for k,v in data.items()):
                raise ValueError('vault_unavailable')
            return data
        except Exception:
            raise ValueError('vault_unavailable') from None
        finally:
            api.CredFree(pointer)

    def write(self,profile_id,secrets):
        name=owned_id(profile_id)
        if not self.available: raise ValueError('vault_unavailable')
        if not isinstance(secrets,dict) or not secrets or any(k not in SECRET_FIELDS or not isinstance(v,str) or not v for k,v in secrets.items()):
            raise ValueError('invalid_credential')
        raw=json.dumps(secrets,separators=(',',':')).encode('utf-8')
        if len(raw)>MAX_BLOB_BYTES: raise ValueError('credential_too_large_for_vault')
        ctypes,Credential,api=self._api(); buffer=(ctypes.c_ubyte*len(raw)).from_buffer_copy(raw)
        value=Credential(Type=1,TargetName=name,CredentialBlobSize=len(raw),CredentialBlob=buffer,Persist=2,UserName='Relay Auditor')
        if not api.CredWriteW(ctypes.byref(value),0): raise ValueError('vault_unavailable')

    def delete(self,profile_id):
        name=owned_id(profile_id)
        if self.available:
            ctypes,_,api=self._api()
            if not api.CredDeleteW(name,1,0) and ctypes.get_last_error()!=1168: raise ValueError('vault_unavailable')
