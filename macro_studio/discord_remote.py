"""Optional Discord bot connection, isolated from Qt and the execution thread."""
import asyncio
from dataclasses import dataclass
import re
import threading
from uuid import uuid4

from PySide6.QtCore import QObject, Signal


def discord_id(value, optional=False):
    value = value.strip()
    match = re.fullmatch(r'<@!?(\d+)>', value)
    if match:
        value = match[1]
    if optional and not value:
        return ''
    if not re.fullmatch(r'[1-9][0-9]{5,19}', value) or int(value) >= 2**64:
        raise ValueError('Indiquez un identifiant Discord numérique valide (Copier l’identifiant).')
    return value


@dataclass
class RemoteConfig:
    enabled: bool = False
    token: str = ''
    channel: str = ''
    owner: str = ''

    def validate(self):
        channel = discord_id(self.channel, optional=not self.enabled)
        owner = discord_id(self.owner, optional=not self.enabled)
        token = self.token.strip()
        if token and (len(token) < 20 or len(token) > 256 or any(c.isspace() for c in token)):
            raise ValueError('Collez le jeton du bot Discord, sans le préfixe Bot.')
        if self.enabled and not token:
            raise ValueError('Renseignez le jeton du bot pour activer les commandes Discord.')
        return RemoteConfig(bool(self.enabled), token, channel, owner)


class DiscordRemote(QObject):
    command_requested = Signal(str, str, str)  # session, action, request ID
    status = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.config = RemoteConfig()
        self.session = ''
        self.loop = self.client = None
        self.thread = None
        self.ready = threading.Event()
        self.shutdown = threading.Event()
        self.pending = {}

    def begin(self):
        self.session = uuid4().hex
        if self.config.enabled:
            self.connect_bot()
        return self.session

    def end(self):
        self.session = ''

    def rejection(self, user, channel, session, action):
        if not self.config.enabled or not self.session or session != self.session:
            return 'Cette commande appartient à une exécution terminée ou désactivée.'
        if str(user) != self.config.owner or str(channel) != self.config.channel:
            return 'Ce bouton est réservé au compte Discord configuré dans Macro Studio.'
        if action not in ('stop', 'resume'):
            return 'Commande inconnue.'
        return ''

    def connect_bot(self):
        if self.thread and self.thread.is_alive() and not self.shutdown.is_set():
            return
        previous = self.thread
        shutdown = self.shutdown = threading.Event()
        token = self.config.token
        self.ready.clear()
        def run():
            try:
                if previous and previous.is_alive():
                    previous.join(timeout=10)
                    if previous.is_alive():
                        self.status.emit('Bot Discord : fermeture précédente en cours, réessayez le test dans quelques secondes.')
                        return
                if not shutdown.is_set():
                    asyncio.run(self._run(token, shutdown))
            except Exception:
                if not shutdown.is_set():
                    self.status.emit('Bot Discord déconnecté : vérifiez le jeton et Internet. Les alertes webhook restent disponibles.')
            finally:
                self.ready.clear()
                self.loop = self.client = None
        self.thread = threading.Thread(target=run, daemon=True, name='discord-remote')
        self.thread.start()

    async def _run(self, token, shutdown):
        import discord
        self.loop = asyncio.get_running_loop()
        self.client = discord.Client(intents=discord.Intents.none(), max_messages=None)

        @self.client.event
        async def on_ready():
            self.ready.set()
            self.status.emit('Bot Discord connecté : commandes Arrêter / Reprendre disponibles.')

        @self.client.event
        async def on_disconnect():
            self.ready.clear()

        @self.client.event
        async def on_resumed():
            self.ready.set()

        @self.client.event
        async def on_interaction(interaction):
            data = interaction.data or {}
            custom = data.get('custom_id', '')
            if not custom.startswith('wms:'):
                return
            parts = custom.split(':')
            if len(parts) != 3:
                return
            _, session, action = parts
            problem = self.rejection(interaction.user.id, interaction.channel_id, session, action)
            if problem:
                await interaction.response.send_message(problem, ephemeral=True)
                return
            await interaction.response.defer(ephemeral=True, thinking=True)
            request_id = uuid4().hex
            future = self.loop.create_future()
            self.pending[request_id] = future
            try:
                self.command_requested.emit(session, action, request_id)
                result = await asyncio.wait_for(future, timeout=8)
            except asyncio.TimeoutError:
                result = 'Macro Studio n’a pas répondu. Vérifiez le PC avant de réessayer.'
            finally:
                self.pending.pop(request_id, None)
            await interaction.followup.send(result, ephemeral=True)

        async with self.client:
            if not shutdown.is_set():
                await self.client.start(token)

    def answer(self, request_id, message):
        loop = self.loop
        if loop and loop.is_running():
            def resolve():
                future = self.pending.get(request_id)
                if future and not future.done():
                    future.set_result(message)
            loop.call_soon_threadsafe(resolve)

    def send(self, content, mention='', session=''):
        """Called only in the notifier's background sender, never in Qt."""
        if not self.ready.wait(8):
            raise ValueError('Bot non connecté ; vérifiez les réglages Discord.')
        loop = self.loop
        if not loop or not self.client:
            raise ValueError('Bot non connecté.')
        future = asyncio.run_coroutine_threadsafe(self._send(content, mention, session), loop)
        try:
            future.result(timeout=12)
        except Exception:
            # Do not retry via webhook: a timed-out send may have reached Discord.
            future.cancel()
            raise ValueError('Envoi par le bot non confirmé : vérifiez le salon et ses permissions.') from None

    async def _send(self, content, mention, session):
        import discord
        channel = self.client.get_partial_messageable(int(self.config.channel))
        view = None
        if session and session == self.session and self.config.enabled:
            view = discord.ui.View(timeout=None)
            view.add_item(discord.ui.Button(label='Arrêter le workflow', style=discord.ButtonStyle.danger,
                                           custom_id=f'wms:{session}:stop'))
            view.add_item(discord.ui.Button(label='Reprendre', style=discord.ButtonStyle.success,
                                           custom_id=f'wms:{session}:resume'))
        allowed = discord.AllowedMentions(everyone=False, roles=False,
                   users=[discord.Object(id=int(mention))] if mention else False, replied_user=False)
        await channel.send(content, allowed_mentions=allowed, view=view)

    def close(self):
        self.end()
        self.shutdown.set()
        self.ready.clear()
        loop, client = self.loop, self.client
        if loop and client and loop.is_running():
            asyncio.run_coroutine_threadsafe(client.close(), loop)
