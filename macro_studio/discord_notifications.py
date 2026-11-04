"""Optional Discord alerts. Credentials stay local; network work never blocks Qt."""
import base64
import ctypes
from ctypes import wintypes
import json
import re
import threading
from urllib import request, error
from datetime import datetime

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QCheckBox, QLineEdit, QPushButton
from . import launcher
from .discord_remote import DiscordRemote, RemoteConfig, discord_id
from .version import VERSION


def validate_url(value):
    value = value.strip()
    if not re.fullmatch(r'https://discord\.com/api(?:/v\d+)?/webhooks/[0-9]{1,25}/[A-Za-z0-9_-]{20,200}', value):
        raise ValueError('Collez une URL de webhook Discord valide (https://discord.com/api/webhooks/…).')
    return value


def protect(data, decrypt=False):
    """Use Windows DPAPI, bound to the signed-in Windows account."""
    class Blob(ctypes.Structure):
        _fields_ = [('size', wintypes.DWORD), ('data', ctypes.POINTER(ctypes.c_ubyte))]
    source = ctypes.create_string_buffer(data)
    incoming = Blob(len(data), ctypes.cast(source, ctypes.POINTER(ctypes.c_ubyte)))
    outgoing = Blob()
    crypt = ctypes.WinDLL('crypt32', use_last_error=True)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    function = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    function.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p,
                         ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    function.restype = wintypes.BOOL
    if not function(ctypes.byref(incoming), None, None, None, None, 1, ctypes.byref(outgoing)):
        raise ValueError('Impossible de protéger les réglages Discord avec ce compte Windows.')
    try:
        return ctypes.string_at(outgoing.data, outgoing.size)
    finally:
        kernel.LocalFree(ctypes.cast(outgoing.data, ctypes.c_void_p))


class NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def message_payload(content, mention=""):
    mention = discord_id(mention, optional=True)
    prefix = f"<@{mention}> " if mention else ""
    return {"content": prefix + content[:1900-len(prefix)],
            "allowed_mentions": {"parse": [], **({"users": [mention]} if mention else {})}}


def send_webhook(url, content, mention=""):
    url = validate_url(url)
    payload = json.dumps(message_payload(content, mention), ensure_ascii=False).encode('utf-8')
    req = request.Request(url + '?wait=true', data=payload, headers={
        'Content-Type': 'application/json', 'User-Agent': 'MacroStudio/' + VERSION}, method='POST')
    try:
        with request.build_opener(NoRedirect()).open(req, timeout=8) as response:
            if not 200 <= response.status < 300:
                raise ValueError('Discord n’a pas confirmé la réception.')
    except error.HTTPError as exc:
        messages = {401: 'Webhook refusé.', 403: 'Accès au salon refusé.',
                    404: 'Webhook supprimé ou introuvable.', 429: 'Limite Discord atteinte ; réessayez plus tard.'}
        raise ValueError(messages.get(exc.code, f'Discord a refusé l’envoi (HTTP {exc.code}).')) from None
    except (error.URLError, OSError):
        raise ValueError('Discord injoignable : vérifiez Internet puis réessayez.') from None


class DiscordNotifier(QObject):
    completed = Signal(bool, str)
    enabled_changed = Signal(bool)

    def __init__(self, parent=None, sender=send_webhook):
        super().__init__(parent)
        self.sender = sender
        self.enabled = False
        self.url = ''
        self.events = {'safety': True, 'error': True, 'stop': True}
        self.mention = ''
        self.remote = DiscordRemote(self)
        self.remote.status.connect(lambda text: self.completed.emit(True, text))
        self.run_active = False
        self.pause_notified = False
        self.final_notified = False
        self.pending = 0
        self.settings = launcher.default_settings()
        self.load_error = ''
        try:
            stored = self.settings.value('discord/credential', '')
            if stored:
                self.url = validate_url(protect(base64.b64decode(stored), decrypt=True).decode('utf-8'))
            self.mention = discord_id(self.settings.value('discord/mention', ''), optional=True)
            token = self.settings.value('discord/bot_credential', '')
            token = protect(base64.b64decode(token), decrypt=True).decode('utf-8') if token else ''
            self.remote.config = RemoteConfig(
                self.settings.value('discord/remote_enabled', False, type=bool), token,
                self.settings.value('discord/channel', ''), self.settings.value('discord/owner', '')).validate()
            self.enabled = self.settings.value('discord/enabled', False, type=bool) and bool(self.url)
            for event in self.events:
                self.events[event] = self.settings.value('discord/' + event, True, type=bool)
        except Exception:
            self.load_error = 'Adresse Discord illisible : renseignez-la de nouveau puis enregistrez.'

    def configure(self, enabled, url, events, mention=None, remote=None):
        url = validate_url(url) if url.strip() else ''
        if enabled and not url:
            raise ValueError('Renseignez l’adresse du webhook avant d’activer les alertes.')
        mention = self.mention if mention is None else discord_id(mention, optional=True)
        remote = self.remote.config if remote is None else remote.validate()
        bot_credential = base64.b64encode(protect(remote.token.encode('utf-8'))).decode('ascii') if remote.token else ''
        credential = base64.b64encode(protect(url.encode('utf-8'))).decode('ascii') if url else ''
        self.settings.setValue('discord/mention', mention)
        self.settings.setValue('discord/bot_credential', bot_credential)
        self.settings.setValue('discord/remote_enabled', remote.enabled)
        self.settings.setValue('discord/channel', remote.channel)
        self.settings.setValue('discord/owner', remote.owner)
        self.settings.setValue('discord/credential', credential)
        self.settings.setValue('discord/enabled', enabled)
        for event in self.events:
            self.settings.setValue('discord/' + event, bool(events[event]))
        self.settings.sync()
        if self.settings.status() != self.settings.Status.NoError:
            raise ValueError('Impossible d’enregistrer les réglages Discord.')
        if remote != self.remote.config:
            self.remote.close()
        self.remote.config = remote
        self.mention = mention
        self.enabled, self.url, self.events = enabled, url, dict(events)
        if not enabled:
            self.remote.end()
        self.enabled_changed.emit(self.enabled)

    def set_enabled(self, enabled):
        if enabled and not self.url:
            raise ValueError('Enregistrez d’abord votre webhook dans Notifications Discord.')
        self.settings.setValue('discord/enabled', enabled)
        self.settings.sync()
        if self.settings.status() != self.settings.Status.NoError:
            raise ValueError('Impossible d’enregistrer le réglage Discord.')
        self.enabled = enabled
        if not enabled:
            self.remote.end()
        elif self.run_active and self.remote.config.enabled:
            self.remote.begin()
        self.enabled_changed.emit(enabled)

    def begin(self):
        self.pause_notified = self.final_notified = False
        self.run_active = True
        if self.enabled and self.remote.config.enabled:
            self.remote.begin()

    def end(self):
        self.run_active = False
        self.remote.end()

    def dispatch(self, url, content, test=False, completion=None, mention_override=None):
        # Bounded background work; no retries which could duplicate an alert.
        if self.pending >= 3:
            self.completed.emit(False, 'Discord : envois déjà en cours, alerte ignorée.')
            if completion:
                completion(False)
            return
        self.pending += 1
        mention = self.mention if mention_override is None else mention_override
        remote = self.enabled and self.remote.config.enabled and not test
        session = self.remote.session
        def run():
            ok, message = True, 'Discord : message de test envoyé.' if test else 'Discord : alerte envoyée.'
            try:
                if remote and self.remote.ready.wait(8):
                    self.remote.send(message_payload(content, mention)['content'], mention, session)
                else:
                    if remote:
                        message = 'Discord : alerte webhook envoyée ; bot indisponible, boutons indisponibles.'
                    if mention:
                        self.sender(url, content, mention=mention)
                    else:
                        self.sender(url, content)
            except ValueError as exc:
                ok, message = False, 'Discord : ' + str(exc)
            except Exception:
                ok, message = False, 'Discord : échec de l’envoi.'
            finally:
                self.pending -= 1
            try:
                self.completed.emit(ok, message)
                if completion:
                    completion(ok)
            except RuntimeError:
                pass  # Application already closed; do not retain a Qt thread.
        threading.Thread(target=run, daemon=True, name='discord-alert').start()

    def alert(self, event, context, reason):
        if not self.enabled or not self.events.get(event):
            return
        if event == 'safety':
            if self.pause_notified:
                return
            self.pause_notified = True
        else:
            if self.final_notified:
                return
            self.final_notified = True
        titles = {'safety': '⚠️ Pause de sécurité', 'error': '❌ Erreur du workflow', 'stop': '⏹ Workflow arrêté avant la fin'}
        # Only status and position are sent, never action parameters or screenshots.
        self.dispatch(self.url, f'{titles[event]} · {datetime.now():%d/%m %H:%M:%S}\n{context[:900]}\n{reason[:700]}')


class DiscordPanel(QWidget):
    def __init__(self, notifier):
        super().__init__()
        self.notifier = notifier
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)
        title = QLabel('NOTIFICATIONS DISCORD')
        title.setProperty('role', 'section')
        layout.addWidget(title)
        help_text = QLabel('Dans votre serveur Discord : Paramètres du serveur → Intégrations → Webhooks → Nouveau webhook.\n'
                           'Choisissez un salon textuel privé, copiez l’URL puis collez-la ici. Activez les notifications du salon sur votre téléphone.')
        help_text.setWordWrap(True)
        layout.addWidget(help_text)
        self.enabled = QCheckBox('Activer les alertes Discord')
        self.enabled.setChecked(notifier.enabled)
        notifier.enabled_changed.connect(self.sync_enabled)
        layout.addWidget(self.enabled)
        self.url = QLineEdit(notifier.url)
        self.url.setEchoMode(QLineEdit.Password)
        self.url.setPlaceholderText('https://discord.com/api/webhooks/…')
        layout.addWidget(self.url)
        self.mention = QLineEdit(notifier.mention)
        self.mention.setPlaceholderText('ID du compte à mentionner, ou <@123456789…> (facultatif)')
        layout.addWidget(QLabel('Mention pour les notifications du téléphone'))
        layout.addWidget(self.mention)
        mention_help = QLabel('Discord → Paramètres → Avancés → Mode développeur, puis clic droit sur votre profil → Copier l’identifiant. Un @pseudo seul ne suffit pas. Les notifications mobiles dépendent aussi des réglages Discord et du téléphone.')
        mention_help.setWordWrap(True)
        layout.addWidget(mention_help)
        self.remote_enabled = QCheckBox('Activer les boutons Arrêter / Reprendre dans Discord')
        self.remote_enabled.setChecked(notifier.remote.config.enabled)
        layout.addWidget(self.remote_enabled)
        self.bot_token = QLineEdit(notifier.remote.config.token)
        self.bot_token.setEchoMode(QLineEdit.Password)
        self.bot_token.setPlaceholderText('Jeton du bot Discord (conservé uniquement sur ce PC)')
        layout.addWidget(self.bot_token)
        self.channel = QLineEdit(notifier.remote.config.channel)
        self.channel.setPlaceholderText('Identifiant du salon du bot')
        layout.addWidget(self.channel)
        self.owner = QLineEdit(notifier.remote.config.owner)
        self.owner.setPlaceholderText('Identifiant du compte autorisé à utiliser les boutons')
        layout.addWidget(self.owner)
        remote_help = QLabel('Créez un bot dans le portail développeur Discord et invitez-le sur votre serveur avec Voir le salon et Envoyer des messages. Aucun accès au contenu des messages n’est nécessaire. Guide : DISCORD.md. Les boutons concernent uniquement l’exécution en cours ; Reprendre agit sur une pause, sans redémarrer un workflow arrêté.')
        remote_help.setWordWrap(True)
        layout.addWidget(remote_help)
        self.events = {}
        for event, label in [('safety', 'Pause de sécurité'), ('error', 'Erreur d’exécution'), ('stop', 'Arrêt avant la fin (bouton Arrêter ou F8)')]:
            checkbox = QCheckBox(label)
            checkbox.setChecked(notifier.events[event])
            self.events[event] = checkbox
            layout.addWidget(checkbox)
        self.save_button = QPushButton('Enregistrer les réglages Discord')
        self.save_button.clicked.connect(self.save)
        layout.addWidget(self.save_button)
        self.test_button = QPushButton('Envoyer un message de test')
        self.test_button.clicked.connect(self.test)
        layout.addWidget(self.test_button)
        self.bot_test_button = QPushButton('Tester la connexion et l’envoi par le bot')
        self.bot_test_button.clicked.connect(self.test_bot)
        layout.addWidget(self.bot_test_button)
        self.status = QLabel(notifier.load_error or 'Aucun message envoyé. Les réglages restent sur ce PC, hors des fichiers workflow.')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        note = QLabel('L’adresse est protégée par votre compte Windows. Les alertes contiennent le nom du document, du module et la position.\n'
                      'Pas d’alerte pour une pause manuelle ou une fin normale. Un PC éteint ou sans Internet ne peut pas prévenir Discord.')
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addStretch()
        notifier.completed.connect(self.result)

    def sync_enabled(self, enabled):
        self.enabled.setChecked(enabled)
        self.status.setText('Alertes Discord activées.' if enabled else 'Alertes Discord désactivées pour vos tests. Webhook conservé.')

    def save(self):
        try:
            self.notifier.configure(self.enabled.isChecked(), self.url.text(), {k: v.isChecked() for k, v in self.events.items()},
                                    self.mention.text(), RemoteConfig(self.remote_enabled.isChecked(), self.bot_token.text(), self.channel.text(), self.owner.text()))
            self.status.setText('Réglages Discord enregistrés.')
            return True
        except ValueError as exc:
            self.status.setText(str(exc))
            return False

    def test(self):
        try:
            url = validate_url(self.url.text())
            mention = discord_id(self.mention.text(), optional=True)
        except ValueError as exc:
            self.status.setText(str(exc))
            return
        self.status.setText('Envoi du message de test…')
        self.test_button.setEnabled(False)
        self.notifier.dispatch(url, '✅ Macro Studio : les notifications Discord fonctionnent.', test=True, mention_override=mention)

    def test_bot(self):
        if not self.save():
            return
        if not self.notifier.enabled or not self.notifier.remote.config.enabled:
            self.status.setText('Activez les alertes et les boutons Discord avant de tester le bot.')
            return
        self.notifier.remote.connect_bot()
        self.bot_test_button.setEnabled(False)
        self.notifier.dispatch(self.notifier.url, '✅ Macro Studio : connexion du bot testée. Les boutons apparaîtront au lancement du workflow.')

    def result(self, ok, message):
        self.status.setText(message)
        self.test_button.setEnabled(True)
        self.bot_test_button.setEnabled(True)
