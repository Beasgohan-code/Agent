"""Language catalog and durable preferences. Catalog presence is NOT translation coverage."""
# Release gate: only fully implemented UI languages may appear or be saved.
# English is the source language. No other full-bot translation is complete yet.
LANGUAGES=(('en','English'),)
NAMES=dict(LANGUAGES)
PICKER={'en':('Choose language','Language saved')}
SCHEMA=("""CREATE TABLE IF NOT EXISTS agent_language_preferences (
    tenant TEXT NOT NULL, scope_id BIGINT NOT NULL CHECK(scope_id<>0),
    language TEXT NOT NULL, actor_id BIGINT NOT NULL CHECK(actor_id>0),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(), PRIMARY KEY(tenant,scope_id))""",)


class LanguageError(RuntimeError):
    """Safe preference validation/storage failure."""


class UnsupportedLanguage(LanguageError):
    """Previously saved locale no longer meets the release gate."""


def supported(saved):
    if not isinstance(saved,str) or saved not in NAMES:
        raise UnsupportedLanguage('Previous language is unavailable. Choose a supported language with /lang.')
    return saved



async def preference(ctx,scope,*,code=None,actor=None):
    if type(scope) is not int or not -(2**63)<scope<2**63 or scope==0:
        raise LanguageError('Invalid language scope.')
    if code is not None and (not isinstance(code,str) or code not in NAMES or type(actor) is not int or not 0<actor<2**63 or scope>0 and actor!=scope):
        raise LanguageError('Invalid language choice or personal identity.')
    db=getattr(ctx,'db',None)
    if db is None:
        if code is not None:
            ctx.chats.put(scope,'language',code)
        saved=ctx.chats.get(scope,'language','en')
        return supported(saved)
    if not db.connected or getattr(db,'_pool',None) is None:
        raise LanguageError('Language storage unavailable. No change confirmed.')
    try:
        async with db._pool.acquire(timeout=5) as conn:
            if code is not None:
                await conn.execute('''INSERT INTO agent_language_preferences(tenant,scope_id,language,actor_id)
                    VALUES($1,$2,$3,$4) ON CONFLICT(tenant,scope_id) DO UPDATE
                    SET language=EXCLUDED.language,actor_id=EXCLUDED.actor_id,updated_at=now()''',db.scope,scope,code,actor,timeout=5)
                return code
            saved=await conn.fetchval('SELECT language FROM agent_language_preferences WHERE tenant=$1 AND scope_id=$2',db.scope,scope,timeout=5)
        return supported('en' if saved is None else saved)
    except LanguageError:
        raise
    except Exception:
        raise LanguageError('Language read or save unconfirmed. Open /lang before retrying.') from None
