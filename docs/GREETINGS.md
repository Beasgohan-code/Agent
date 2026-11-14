# Greeting safety and current limitations

Welcome rendering now substitutes only the original template placeholders in
one pass. Member names/chat titles that contain `{chat}` or `{count}` stay
literal. Template/value HTML remains escaped except for the generated mention.
The watcher sends with explicit HTML parse mode. Expanded markup exceeding a
conservative 4000 UTF-16-unit bound is refused before sending, not truncated.
Failures log only the error category, not raw update/template/provider details.

Join/leave detection uses actual membership, not just MEMBER status. Owners and
administrators are members; restricted participants use is_member when supplied.
Unknown restricted status does not fabricate a join or departure. Promotions,
demotions and restriction changes within membership do not trigger greetings.

`/setwelcome` and `/goodbye text` preserve multiline text and reject over 1500
characters rather than silently storing only a prefix. `/welcome on|off` and
`/goodbye on|off` reject extra arguments instead of ignoring them. Commands
require personal identity and existing administrator permissions. Welcome studio
shows the escaped layout outside table cells; update panels use premium theme
icons and normal sender fallback. Literal goodbye text beginning `on`/`off`
with extra words is reserved/rejected to avoid ambiguous toggle mistakes.

Settings persistence remains background-flushed ChatStore. This is not a
confirmed SQL-write upgrade. A valid stored template can still expand beyond
the send limit depending on member/chat names, and Telegram can refuse delivery.
No failed-send retry, deduplication across replicas, automatic default greeting,
24/7 guarantee or live Telegram validation was added.

## Confirmed PostgreSQL settings (supersedes persistence notes above)

Normal runtime now uses `agent_greetings`, keyed by tenant/group/kind. Text saves
and toggles await SQL before success. Toggle upserts only enabled state for an
existing row, so stale legacy text cannot overwrite a newer layout. A first
toggle seeds text from existing PostgreSQL document settings; explicit saves
replace text and enable that greeting. Display and membership events read the
row each time. Missing dedicated rows retain legacy document behavior until
first save/toggle; configured-database failures do not fall back to that data.

Database outages suppress event delivery and return unconfirmed command panels.
Timeouts can have ambiguous commit outcomes: inspect settings before retrying.
Standalone db=None compatibility helpers remain for tests, not normal runtime.
No local JSON migration or changes to production were performed. There is still
no guaranteed send/retry, event deduplication or immutable settings history.
