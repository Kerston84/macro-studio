# Contribuer

Les corrections, améliorations d’interface et retours reproductibles sont les bienvenus.

## Développement

1. Créez un fork puis une branche pour votre modification.
2. Installez l’environnement Windows Python 3.12 décrit dans README.md.
3. Reproduisez le problème avec un exemple synthétique, sans identifiants personnels.
4. Modifiez le code et ajoutez un test pertinent lorsqu’il protège un comportement.
5. Exécutez `python -m pytest -q` avec `QT_QPA_PLATFORM=offscreen`.
6. Ouvrez une pull request décrivant le problème, le résultat et les vérifications.

Les tests ne doivent ni cliquer sur le Bureau, ni saisir dans une application réelle, ni envoyer de messages Discord. Utilisez les backends simulés et les réglages temporaires existants. Les nouvelles fonctions doivent respecter F8, l’arrêt coopératif et les pauses de sécurité.

## Signaler un problème

Indiquez la version de Windows et de l’application, les étapes, le résultat attendu et le résultat obtenu. Retirez les noms de compte, messages privés, captures personnelles et jetons des journaux. Préférez un workflow minimal contenant uniquement des actions factices.

## Licence des contributions

En proposant une contribution, vous acceptez de la distribuer sous la licence MIT du projet. N’intégrez pas de code ou d’images sans droit de redistribution.
