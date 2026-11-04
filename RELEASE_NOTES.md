# Proposition de première publication : v0.23.0

Statut prévu : **Pre-release**. Aucun binaire n’est présenté comme validé sur une machine Windows propre.

Éditeur visuel de macros Windows avec workflows, reconnaissance d’images, règles de popups, suivi flottant, OCR et Discord facultatif. Les notifications peuvent mentionner un compte ; un bot optionnel propose Arrêter/Reprendre.

## Validation

374 tests locaux réussis. Discord et les entrées souris/clavier sont simulés. Le test sur serveur Discord réel reste à effectuer. Lancement et installation des binaires non revalidés après un blocage de politique Windows 4551 rencontré avec une livraison précédente. Les binaires ne sont pas signés.

## Fichiers à joindre après revue

- WindowsMacroStudio-Setup-0.23.0-x64.exe
- WindowsMacroStudio-Portable-0.23.0-x64.zip
- LICENSE
- SHA256SUMS.txt
- DISCORD.md et BILAN-TESTS.md
- LANCEMENT-NON-VALIDE.txt

Ne pas joindre l’ancienne archive source de travail : elle contient des documents de développement inutiles au dépôt. L’archive source de GitHub sera générée à partir du dépôt propre. Ne pas activer une publication automatique de binaires tant que leur validation reste incomplète.
