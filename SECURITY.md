# Signalements de sécurité

N’incluez jamais de webhook, jeton de bot, mot de passe ou workflow confidentiel dans une issue publique.

Si le dépôt propose « Report a vulnerability » dans son onglet Security, utilisez ce canal privé. Sinon, ouvrez une issue sans détails exploitables pour demander un moyen de contact privé. Ne publiez pas le secret pour démontrer le problème. En cas de fuite, révoquez le jeton ou le webhook auprès de Discord et remplacez-le sur votre PC.

L’application reçoit uniquement deux commandes Discord : Arrêter et Reprendre. Elles sont limitées au compte, au salon et à l’exécution configurés. Elle n’expose pas de shell distant ni de serveur HTTP entrant.

La version actuelle est une préversion. Aucun délai de réponse ou de correction n’est garanti. Les réglages locaux sont protégés par DPAPI et restent liés au compte Windows. Les fichiers workflow ne sont pas chiffrés : ne les utilisez pas pour conserver des secrets.
