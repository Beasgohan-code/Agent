from agent.ui.theme import Theme
from agent.ui.workers import overview, callback, selected, lookup


def test_unavailable_selected_tools_are_explained_not_silently_hidden():
    theme = Theme(worker_plugins=('encoder', 'ai_agent'))
    screen = overview(None, theme, active={'warn', 'encode'})
    assert 'AI Agent' in screen.rich_text
    assert 'Not registered' in screen.rich_text
    assert 'worker:ai_agent:0' not in str(screen.keyboard)
    assert 'worker:availability' in str(screen.keyboard)


def test_availability_is_honest_about_registration_not_connectivity():
    theme = Theme(worker_plugins=('encoder', 'ai_agent'))
    screen = callback('worker:availability', None, theme, active={'encode', 'warn'})
    assert screen is not None
    assert 'Commands registered' in screen.rich_text
    assert 'Not registered' in screen.rich_text
    assert 'provider connectivity' in screen.rich_text
    assert 'Meiko' not in screen.rich_text
    assert callback('worker:availability', None, Theme(), active={'encode'}) is None


def test_unknown_registry_state_is_not_reported_as_disabled_or_ready():
    screen = callback('worker:availability', None, Theme(worker_plugins=('encoder',)), active=None)
    assert 'Unknown' in screen.rich_text
    assert 'Commands registered' not in screen.rich_text


def test_wildcard_workers_present_compatible_live_features_only():
    theme = Theme(worker_plugins=('*',))
    assert 'encoder' in selected(theme)
    assert 'ai_agent' in selected(theme)
    screen = overview(None, theme, active={'encode', 'ask', 'clone', 'plans', 'warn'})
    assert '/encode' in screen.rich_text
    assert '/ask' in screen.rich_text
    assert '/clone' not in screen.rich_text
    assert '/plans' not in screen.rich_text
    assert callback('worker:encoder:0', None, theme, active={'encode'}) is not None
    assert '/encode' in lookup('encode', None, theme, active={'encode'}).rich_text


def test_refresh_uses_current_registry_and_rebuilds_action_buttons():
    theme = Theme(worker_plugins=('encoder',))
    before = callback('worker:availability', None, theme, active={'encode'})
    after = callback('worker:availability', None, theme, active=set())
    assert before.rich_text != after.rich_text
    assert 'Commands registered' not in after.rich_text
    home = overview(None, theme, active=set())
    assert 'worker:guide:encoder' not in str(home.keyboard)
    assert 'worker:encoder:0' not in str(home.keyboard)
    assert 'worker:availability' in str(home.keyboard)


def test_availability_respects_unicode_mode_and_has_no_mutations():
    theme = Theme({}, worker_plugins=('encoder',))
    screen = callback('worker:availability', None, theme, active={'encode'})
    assert '<tg-emoji' not in screen.rich_text
    assert '<tg-emoji' not in screen.rich_text.classic
    for row in screen.keyboard.inline_keyboard:
        for button in row:
            assert not button.icon_custom_emoji_id
            assert button.callback_data in {'worker:availability', 'menu:home', 'menu:help', 'worker:encoder:0'}
            if button.callback_data == 'worker:encoder:0':
                assert callback(button.callback_data, None, theme, active={'encode'}) is not None
