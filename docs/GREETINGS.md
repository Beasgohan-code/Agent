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
