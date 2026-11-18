"""Language catalog and durable preferences. Catalog presence is NOT translation coverage."""
LANGUAGES=tuple(tuple(line.split('|',1)) for line in '''en|English
ml|മലയാളം
hi|हिन्दी
ta|தமிழ்
te|తెలుగు
kn|ಕನ್ನಡ
bn|বাংলা
mr|मराठी
gu|ગુજરાતી
pa|ਪੰਜਾਬੀ
ur|اردو
ar|العربية
fr|Français
de|Deutsch
es|Español
pt|Português
ru|Русский
zh|中文
ja|日本語
ko|한국어
it|Italiano
nl|Nederlands
pl|Polski
uk|Українська
tr|Türkçe
fa|فارسی
id|Bahasa Indonesia
ms|Bahasa Melayu
vi|Tiếng Việt
th|ไทย
ne|नेपाली
si|සිංහල
my|မြန်မာ
km|ខ្មែរ
lo|ລາວ
bo|བོད་སྐད་
dz|རྫོང་ཁ
or|ଓଡ଼ିଆ
as|অসমীয়া
sa|संस्कृतम्
sd|سنڌي
ps|پښتو
ku|Kurdî
he|עברית
el|Ελληνικά
ro|Română
hu|Magyar
cs|Čeština
sk|Slovenčina
sl|Slovenščina
hr|Hrvatski
sr|Српски
bs|Bosanski
bg|Български
mk|Македонски
sq|Shqip
sv|Svenska
da|Dansk
no|Norsk
fi|Suomi
is|Íslenska
et|Eesti
lv|Latviešu
lt|Lietuvių
mt|Malti
ga|Gaeilge
cy|Cymraeg
gd|Gàidhlig
br|Brezhoneg
eu|Euskara
ca|Català
gl|Galego
af|Afrikaans
sw|Kiswahili
am|አማርኛ
so|Soomaali
ha|Hausa
yo|Yorùbá
ig|Igbo
zu|isiZulu
xh|isiXhosa
st|Sesotho
sn|chiShona
rw|Kinyarwanda
mg|Malagasy
ny|Chichewa
om|Afaan Oromoo
ti|ትግርኛ
az|Azərbaycanca
hy|Հայերեն
ka|ქართული
kk|Қазақша
ky|Кыргызча
uz|Oʻzbekcha
tg|Тоҷикӣ
tk|Türkmençe
mn|Монгол
fil|Filipino
jv|Basa Jawa
su|Basa Sunda'''.splitlines())
NAMES=dict(LANGUAGES)
# Only language-picker copy is translated so far. Other commands stay English.
PICKER={
    'en':('Choose language','Language saved'),
    'ml':('ഭാഷ തിരഞ്ഞെടുക്കുക','ഭാഷ സേവ് ചെയ്തു'),
    'hi':('भाषा चुनें','भाषा सहेजी गई'),
    'ta':('மொழியைத் தேர்ந்தெடுக்கவும்','மொழி சேமிக்கப்பட்டது'),
}
SCHEMA=("""CREATE TABLE IF NOT EXISTS agent_language_preferences (
    tenant TEXT NOT NULL, scope_id BIGINT NOT NULL CHECK(scope_id<>0),
    language TEXT NOT NULL, actor_id BIGINT NOT NULL CHECK(actor_id>0),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(), PRIMARY KEY(tenant,scope_id))""",)


class LanguageError(RuntimeError):
    """Safe preference validation/storage failure."""


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
        return saved if saved in NAMES else 'en'
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
        return saved if saved in NAMES else 'en'
    except Exception:
        raise LanguageError('Language read or save unconfirmed. Open /lang before retrying.') from None
