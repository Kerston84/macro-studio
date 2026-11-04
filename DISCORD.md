# Notifications et commandes Discord — 0.23.0

## Mention sur le téléphone

1. Dans Discord, activez **Paramètres utilisateur → Avancés → Mode développeur**.
2. Sur votre profil, utilisez **Copier l’identifiant utilisateur**.
3. Dans Macro Studio → **Notifications Discord**, collez cet identifiant dans **Mention pour les notifications du téléphone**. Le format `<@identifiant>` est également accepté ; un simple `@pseudo` ne suffit pas.
4. Conservez votre webhook, activez les alertes, enregistrez et utilisez **Envoyer un message de test**.

Les alertes et comptes rendus mentionnent uniquement ce compte. Les mentions de rôle, `@everyone` et `@here` provenant des noms de documents ou du texte sont désactivées. Pour recevoir une notification sur le téléphone, autorisez les notifications Discord dans le système mobile et dans le salon ; le mode Ne pas déranger et les réglages de notifications peuvent empêcher une notification.

Documentation : [mentions autorisées](https://docs.discord.com/developers/resources/message#allowed-mentions-object).

## Boutons Arrêter et Reprendre

Un webhook seul envoie les alertes. Les boutons interactifs nécessitent un bot connecté à Macro Studio. Le PC doit rester allumé, l’application ouverte et Internet disponible. Aucun serveur public ni redirection de port n’est requis : le logiciel se connecte à Discord.

1. Ouvrez le [portail développeur Discord](https://discord.com/developers/applications), créez une application puis ouvrez **Bot**.
2. Récupérez ou réinitialisez le **jeton du bot**. Collez-le uniquement dans le champ masqué **Jeton du bot Discord** de Macro Studio. N’utilisez pas le jeton de votre compte personnel. Le logiciel protège le jeton avec votre compte Windows ; il reste hors des workflows et des archives de livraison.
3. Dans **Installation** ou **OAuth2 → URL Generator**, créez un lien d’installation sur votre serveur avec le scope **bot** et les permissions **View Channels / Voir les salons** et **Send Messages / Envoyer des messages**. Le bot doit aussi être autorisé à voir le salon choisi par ses permissions locales. Utilisez un salon textuel normal. Les intents privilégiés, notamment Message Content, peuvent rester désactivés. Ne configurez pas d’URL Interactions Endpoint : les clics arrivent par la connexion du bot.
4. Dans Discord, faites **Copier l’identifiant du salon** sur le salon souhaité. Collez-le dans **Identifiant du salon du bot**.
5. Collez votre identifiant utilisateur dans **Identifiant du compte autorisé à utiliser les boutons**. Vous pouvez utiliser le même compte que pour la mention.
6. Cochez **Activer les boutons Arrêter / Reprendre dans Discord**, conservez **Activer les alertes Discord**, puis enregistrez. Utilisez **Tester la connexion et l’envoi par le bot**. Ce test envoie un message ; il ne lance aucune macro.
7. Lancez un workflow : le bot publie un message avec **Arrêter le workflow** et **Reprendre**. Les alertes publiées pendant cette exécution proposent aussi ces boutons.

**Arrêter** interrompt l’exécution en cours comme le bouton local ou F8. **Reprendre** reprend une exécution en pause ; il ne redémarre pas un workflow arrêté ou terminé. La réponse du bot confirme le résultat de la commande uniquement à la personne qui a cliqué. Si la fenêtre cible a changé, la reprise est refusée. La protection contre un obstacle sur la zone du clic reste active et peut remettre le workflow en pause.

Les boutons sont réservés au compte et au salon configurés, et à l’exécution qui les a créés. Un ancien message ne commande jamais une nouvelle exécution. Désactiver les alertes avec le bouton rapide désactive aussi les commandes de l’exécution ; il faudra une nouvelle alerte pour recevoir de nouveaux boutons après réactivation. Une fois le bot ou le PC hors ligne, Discord ne peut plus exécuter ces commandes.

Si le bot n’est pas connecté au moment de l’envoi, le logiciel utilise le webhook et indique que les boutons sont indisponibles. Si un envoi du bot a commencé mais n’est pas confirmé, aucun deuxième message automatique n’est envoyé pour éviter un doublon. Consultez le journal et retestez la connexion. Les messages de fin ne proposent pas de commande active ; les anciens boutons sont refusés.

Documentation : [premier bot Discord](https://docs.discord.com/developers/quick-start/getting-started), [interactions Discord](https://docs.discord.com/developers/interactions/receiving-and-responding).

## Validation de cette livraison

Les tests utilisent des événements et des messages simulés. Aucun jeton réel n’est inclus et aucune notification réelle n’a été envoyée pendant le développement. Une vérification sur votre serveur reste à effectuer avec les deux boutons de test puis un workflow de test.
