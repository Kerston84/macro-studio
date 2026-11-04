import json
import threading
from urllib import error
import pytest
from PySide6.QtTest import QTest
from macro_studio import discord_notifications as d
from macro_studio.app import MainWindow
from test_ui import app

URL = 'https://discord.com/api/webhooks/123456789/' + 'x' * 60


def test_quick_disable_persists_and_keeps_webhook(monkeypatch):
    window = MainWindow()
    window.discord.configure(True, URL, dict(window.discord.events))
    assert window.discord_toggle.isChecked()
    window.set_running(True)
    assert window.discord_toggle.isEnabled()
    window.discord_toggle.click()
    assert not window.discord.enabled
    assert not window.discord_panel.enabled.isChecked()
    restored = d.DiscordNotifier()
    assert not restored.enabled and restored.url == URL
    sent = []
    monkeypatch.setattr(window.discord, 'dispatch', lambda *a: sent.append(a))
    for event in ('safety', 'error', 'stop'):
        window.discord.alert(event, 'test', 'test')
    assert not sent
    window.discord_toggle.click()
    assert window.discord.enabled and window.discord_panel.enabled.isChecked()
    assert d.DiscordNotifier().enabled
    window.set_running(False)
    window.close()


def test_quick_enable_without_webhook_is_rejected():
    window = MainWindow()
    window.discord_toggle.click()
    assert not window.discord.enabled and not window.discord_toggle.isChecked()
    assert 'webhook' in window.journal.toPlainText()
    window.close()


@pytest.mark.parametrize('url', ['http://discord.com/api/webhooks/1/' + 'x'*60,
    URL + '?wait=false', URL.replace('discord.com', 'evil.example'),
    URL.replace('discord.com', 'discord.com@evil.example'), URL + '/extra', ''])
def test_reject_unsafe_webhook_urls(url):
    with pytest.raises(ValueError):
        d.validate_url(url)


def test_local_settings_encrypt_secret_and_restore():
    notifier = d.DiscordNotifier()
    assert not notifier.enabled
    notifier.configure(True, URL, dict(notifier.events))
    stored = notifier.settings.value('discord/credential')
    assert URL not in stored and 'x'*60 not in stored
    restored = d.DiscordNotifier()
    assert restored.enabled and restored.url == URL
    notifier.configure(False, '', dict(notifier.events))
    assert d.DiscordNotifier().url == ''


def test_invalid_enabled_configuration_keeps_existing_settings():
    notifier = d.DiscordNotifier()
    with pytest.raises(ValueError):
        notifier.configure(True, '', notifier.events)
    assert not notifier.enabled


def test_http_payload_and_timeout_without_real_network(monkeypatch):
    captured = {}
    class Response:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *args): pass
    class Opener:
        def open(self, req, timeout):
            captured.update(url=req.full_url, payload=json.loads(req.data), timeout=timeout)
            return Response()
    monkeypatch.setattr(d.request, 'build_opener', lambda *a: Opener())
    d.send_webhook(URL, '@everyone ' + 'é'*2500)
    assert captured['payload']['allowed_mentions'] == {'parse': []}
    assert len(captured['payload']['content']) == 1900
    assert captured['timeout'] == 8
    assert captured['url'] == URL + '?wait=true'
    assert d.NoRedirect().redirect_request(None, None, 302, '', {}, 'https://evil.example') is None


@pytest.mark.parametrize('code', [403, 404, 429, 500])
def test_errors_never_expose_webhook(monkeypatch, code):
    class Opener:
        def open(self, *a, **kw):
            raise error.HTTPError(URL, code, URL, {}, None)
    monkeypatch.setattr(d.request, 'build_opener', lambda *a: Opener())
    with pytest.raises(ValueError) as exc:
        d.send_webhook(URL, 'test')
    assert URL not in str(exc.value)


def test_background_send_does_not_block_ui():
    entered, release = threading.Event(), threading.Event()
    def sender(url, text):
        entered.set()
        release.wait(2)
    notifier = d.DiscordNotifier(sender=sender)
    results = []
    notifier.completed.connect(lambda ok, message: results.append(ok))
    notifier.dispatch(URL, 'test', test=True)
    assert entered.wait(1) and notifier.pending == 1
    app.processEvents()
    assert results == []
    release.set()
    for _ in range(100):
        QTest.qWait(10)
        if results: break
    assert results == [True]


def test_alert_dedup_and_event_preferences(monkeypatch):
    notifier = d.DiscordNotifier()
    sent = []
    monkeypatch.setattr(notifier, 'dispatch', lambda *args: sent.append(args))
    notifier.alert('safety', 'module', 'pause')
    assert not sent
    notifier.enabled, notifier.url = True, URL
    notifier.begin()
    notifier.alert('safety', 'module', 'pause')
    notifier.alert('safety', 'module', 'pause')
    assert len(sent) == 1
    notifier.pause_notified = False
    notifier.alert('safety', 'module', 'pause')
    notifier.alert('error', 'module', 'erreur')
    notifier.alert('stop', 'module', 'arrêt')
    assert len(sent) == 3
    notifier.begin()
    notifier.events['stop'] = False
    notifier.alert('stop', 'module', 'arrêt')
    assert len(sent) == 3


def test_window_event_routing_and_manual_pause_ignored(monkeypatch):
    window = MainWindow()
    events = []
    monkeypatch.setattr(window.discord, 'alert', lambda *args: events.append(args))
    window.pause_state_changed(True, 'Pause manuelle')
    window.execution_result('Terminé')
    assert not events
    window.pause_state_changed(True, 'Sécurité : obstacle')
    window.execution_result('Erreur : texte confidentiel')
    window.execution_result('Arrêté')
    assert [a[0] for a in events] == ['safety', 'error', 'stop']
    assert all('confidentiel' not in a[2] for a in events)
    window.discord.pause_notified = True
    window.pause_state_changed(False, 'Reprise')
    assert not window.discord.pause_notified
    window.close()


def test_panel_test_sends_only_on_button_click(monkeypatch):
    notifier = d.DiscordNotifier()
    sent = []
    monkeypatch.setattr(notifier, 'dispatch', lambda *a, **kw: sent.append((a, kw)))
    panel = d.DiscordPanel(notifier)
    panel.url.setText(URL)
    assert not sent
    panel.test_button.click()
    assert len(sent) == 1 and sent[0][1]['test']
    assert not panel.test_button.isEnabled()
    panel.result(True, 'OK')
    assert panel.test_button.isEnabled()
    panel.close()
