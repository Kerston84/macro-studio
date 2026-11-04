import asyncio
from types import SimpleNamespace
import threading

import pytest
from PySide6.QtTest import QTest
from macro_studio import discord_notifications as d
from macro_studio.discord_remote import DiscordRemote, RemoteConfig, discord_id
from macro_studio.run_control import RunControl
from macro_studio.app import MainWindow
from test_ui import app

URL = 'https://discord.com/api/webhooks/123456789/' + 'x' * 60
USER, CHANNEL = '123456789012345678', '234567890123456789'
TOKEN = 'fake_bot_token_for_offline_tests_only'


def configured():
    notifier = d.DiscordNotifier()
    notifier.configure(True, URL, notifier.events, '<@' + USER + '>',
                       RemoteConfig(True, TOKEN, CHANNEL, USER))
    return notifier


def test_mention_payload_allows_only_selected_user():
    payload = d.message_payload('@everyone <@&123456> ' + 'é' * 2200, USER)
    assert payload['content'].startswith('<@' + USER + '> ')
    assert len(payload['content']) == 1900
    assert payload['allowed_mentions'] == {'parse': [], 'users': [USER]}
    assert d.message_payload('hello')['allowed_mentions'] == {'parse': []}
    assert discord_id('<@!' + USER + '>') == USER


@pytest.mark.parametrize('value', ['@everyone', '@pseudo', '<@&123456789>', 'https://evil.test', '0', str(2**64)])
def test_invalid_mentions_rejected_before_save(value):
    notifier = d.DiscordNotifier()
    with pytest.raises(ValueError):
        notifier.configure(True, URL, notifier.events, value)
    assert not notifier.enabled and not notifier.url


def test_settings_roundtrip_bot_token_is_encrypted_and_remote_off_by_default():
    assert not d.DiscordNotifier().remote.config.enabled
    notifier = configured()
    stored = notifier.settings.value('discord/bot_credential')
    assert TOKEN not in stored
    restored = d.DiscordNotifier()
    assert restored.remote.config == RemoteConfig(True, TOKEN, CHANNEL, USER)
    assert restored.mention == USER
    with pytest.raises(ValueError):
        notifier.configure(True, URL, notifier.events, USER, RemoteConfig(True, '', CHANNEL, USER))
    assert notifier.remote.config.token == TOKEN
    assert d.DiscordNotifier().remote.config.token == TOKEN


def test_session_authorization_and_disabled_controls(monkeypatch):
    notifier = configured()
    remote = notifier.remote
    monkeypatch.setattr(remote, 'connect_bot', lambda: None)
    notifier.begin()
    session = remote.session
    assert not remote.rejection(USER, CHANNEL, session, 'stop')
    assert remote.rejection('345678901234567890', CHANNEL, session, 'stop')
    assert remote.rejection(USER, '345678901234567890', session, 'stop')
    assert remote.rejection(USER, CHANNEL, session, 'start')
    notifier.end()
    assert remote.rejection(USER, CHANNEL, session, 'resume')
    notifier.begin()
    assert remote.session != session
    assert remote.rejection(USER, CHANNEL, session, 'stop')
    notifier.set_enabled(False)
    assert not remote.session


def test_bot_message_has_two_buttons_and_no_buttons_after_end():
    async def scenario():
        remote = DiscordRemote()
        remote.config = RemoteConfig(True, TOKEN, CHANNEL, USER)
        remote.session = 'current'
        sent = []
        async def send(content, **kwargs):
            sent.append((content, kwargs))
        remote.client = SimpleNamespace(get_partial_messageable=lambda channel: SimpleNamespace(send=send))
        await remote._send('<@' + USER + '> alert', USER, 'current')
        view = sent[0][1]['view']
        assert [b.label for b in view.children] == ['Arrêter le workflow', 'Reprendre']
        assert [b.custom_id for b in view.children] == ['wms:current:stop', 'wms:current:resume']
        assert sent[0][1]['allowed_mentions'].to_dict() == {'users': [int(USER)], 'parse': []}
        remote.end()
        await remote._send('finished', USER, 'current')
        assert sent[1][1]['view'] is None
    asyncio.run(scenario())


def test_interactions_deferred_ack_and_qt_result_without_network(monkeypatch):
    import discord
    remote = DiscordRemote()
    remote.config = RemoteConfig(True, TOKEN, CHANNEL, USER)
    remote.session = 'session'
    events = []
    class Response:
        async def send_message(self, text, **kwargs): events.append(('rejected', text, kwargs))
        async def defer(self, **kwargs): events.append(('defer', kwargs))
    class Followup:
        async def send(self, text, **kwargs): events.append(('answer', text, kwargs))
    class Client:
        def __init__(self, **kwargs):
            assert kwargs['intents'].value == 0
            self.events = {}
        def event(self, function): self.events[function.__name__] = function; return function
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def start(self, token):
            assert token == TOKEN
            interaction = SimpleNamespace(data={'custom_id': 'wms:session:stop'},
                user=SimpleNamespace(id=int(USER)), channel_id=int(CHANNEL), response=Response(), followup=Followup())
            await self.events['on_interaction'](interaction)
            interaction.user.id = 345678901234567890
            await self.events['on_interaction'](interaction)
    monkeypatch.setattr(discord, 'Client', Client)
    commands = []
    def command(session, action, request_id):
        commands.append((session, action))
        remote.answer(request_id, 'Arrêt demandé.')
    remote.command_requested.connect(command)
    asyncio.run(remote._run(TOKEN, threading.Event()))
    assert commands == [('session', 'stop')]
    assert events[0] == ('defer', {'ephemeral': True, 'thinking': True})
    assert events[1] == ('answer', 'Arrêt demandé.', {'ephemeral': True})
    assert events[2][0] == 'rejected'
    assert not remote.pending
    remote.loop = remote.client = None


def test_notifier_routes_to_bot_and_keeps_mention(monkeypatch):
    notifier = configured()
    notifier.remote.session = 'run'
    notifier.remote.ready.set()
    sent = []
    monkeypatch.setattr(notifier.remote, 'send', lambda *args: sent.append(args))
    notifier.dispatch(URL, 'Safety')
    for _ in range(100):
        QTest.qWait(10)
        if not notifier.pending: break
    assert sent == [('<@' + USER + '> Safety', USER, 'run')]


def test_offline_bot_falls_back_to_webhook_without_buttons(monkeypatch):
    notifier = configured()
    monkeypatch.setattr(notifier.remote.ready, 'wait', lambda timeout: False)
    sent = []
    notifier.sender = lambda *args, **kwargs: sent.append((args, kwargs))
    notifier.dispatch(URL, 'Safety')
    for _ in range(100):
        QTest.qWait(10)
        if not notifier.pending: break
    assert sent == [((URL, 'Safety'), {'mention': USER})]


def test_remote_commands_stop_resume_and_respect_safety(monkeypatch):
    window = MainWindow()
    notifier = window.discord
    notifier.enabled = True
    remote = notifier.remote
    remote.config = RemoteConfig(True, TOKEN, CHANNEL, USER)
    remote.session = 'run'
    remote.pending['request'] = SimpleNamespace(done=lambda: False)
    results = []
    monkeypatch.setattr(remote, 'answer', lambda request, text: results.append(text))
    control = RunControl()
    window.worker = SimpleNamespace(control=control, stop_event=control.stop, isRunning=lambda: True)
    control.pause('Safety')
    control.guard = SimpleNamespace(reason=lambda: 'Cible masquée', arm=lambda: None)
    control.safety_enabled = control.armed = True
    window.discord_command('run', 'resume', 'request')
    assert control.paused and 'refusée' in results[-1]
    control.guard.reason = lambda: None
    window.discord_command('run', 'resume', 'request')
    assert not control.paused and 'repris' in results[-1]
    window.discord_command('old', 'stop', 'request')
    assert not control.is_set()
    window.discord_command('run', 'stop', 'expired')
    assert not control.is_set()
    window.discord_command('run', 'stop', 'request')
    assert control.is_set()
    control.paused = True
    window.discord_command('run', 'resume', 'request')
    assert control.paused
    window.worker = None
    window.close()


def test_panel_saves_mention_and_remote_fields_without_connecting():
    notifier = d.DiscordNotifier()
    panel = d.DiscordPanel(notifier)
    panel.enabled.setChecked(True)
    panel.url.setText(URL)
    panel.mention.setText('<@' + USER + '>')
    panel.remote_enabled.setChecked(True)
    panel.bot_token.setText(TOKEN)
    panel.channel.setText(CHANNEL)
    panel.owner.setText(USER)
    assert panel.save()
    assert notifier.mention == USER and notifier.remote.config.enabled
    assert notifier.remote.thread is None
    panel.close()
