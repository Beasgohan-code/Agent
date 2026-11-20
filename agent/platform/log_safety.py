"""Bounded best-effort log sanitization, not a substitute for avoiding secret collection."""
import re

REDACTED='[redacted]'
_SENSITIVE=re.compile(r'token|password|passwd|secret|credential|authorization|api_?hash|api_?key|session_?string|private_?key|database_?url|access_?key|refresh_?key|message_?text|raw_?update|payload|prompt|caption|content',re.I)
_TOKEN=re.compile(r'(?<![\w-])\d{5,16}:[A-Za-z0-9_-]{20,}')
_URL=re.compile(r'(?i)\b(postgres(?:ql)?|redis|rediss|https?)://[^\s/@]+:[^\s/@]+@[^\s<>]+')
_BEARER=re.compile(r'(?i)\bBearer\s+[A-Za-z0-9._~+/-]+=*')
_ASSIGN=re.compile(r'(?i)\b(token|password|passwd|secret|session_string|api_hash|authorization|api_key)\s*[=:]\s*[^\s,;]+')


def scrub_text(text):
    text=_TOKEN.sub(REDACTED,text)
    text=_URL.sub('[credential URL redacted]',text)
    text=_BEARER.sub('Bearer '+REDACTED,text)
    return _ASSIGN.sub(lambda match:match[1]+'='+REDACTED,text)


def safe_value(value,depth=0):
    if value is None or type(value) in (bool,int,float):
        return value
    if isinstance(value,BaseException):
        return type(value).__name__[:80]
    if isinstance(value,str):
        text=scrub_text(value[:8192])
        text=''.join(char if char.isprintable() or char=='\n' else ' ' for char in text)
        return text[:256]+(' [truncated]' if len(text)>256 or len(value)>8192 else '')
    if depth>=3:
        return '[nested data omitted]'
    if isinstance(value,dict):
        return safe_fields(value,depth+1)
    if isinstance(value,(list,tuple)):
        result=[safe_value(item,depth+1) for item in value[:8]]
        if len(value)>8:
            result.append('[items omitted]')
        return result
    # Never stringify arbitrary objects: credentials may live in repr/str.
    return '['+type(value).__name__[:64]+']'


def safe_fields(fields,depth=0):
    result={}
    for index,(key,value) in enumerate(fields.items()):
        if index>=24:
            result['omitted']='Additional fields omitted'
            break
        key=key if isinstance(key,str) else type(key).__name__
        label=scrub_text(key[:256])[:64]
        result[label]=REDACTED if _SENSITIVE.search(key) else safe_value(value,depth)
    return result
