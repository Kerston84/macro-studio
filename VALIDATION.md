# Validation de la copie destinée à GitHub

Date : 4 novembre 2026. Version : 0.23.1. Environnement : Windows et Python 3.12.

- 374 tests réussis en 50,91 secondes depuis cette copie, avec un avertissement audioop de la bibliothèque Discord sous Python 3.12.
- Paquet wheel construit avec les métadonnées MIT et le fichier LICENSE.
- Réseau Discord et entrées souris/clavier simulés dans les tests. OCR sur image synthétique.
- Sources contrôlées pour les chemins de profil, identifiants personnels connus et webhooks réels. Les workflows personnels et les fichiers de compilation sont exclus.
- La CI Windows de la version 0.23.0 a réussi sur GitHub (374 tests). Le renommage 0.23.1 est vérifié séparément avant publication.
- Lancement et installation des binaires non revalidés ; serveur Discord réel non testé. Voir README.md.

## Renommage 0.23.1

375 tests réussis en 42,86 secondes. Le nouveau test vérifie la réutilisation du dossier de workflows existant après le changement de nom. Les titres, messages Discord, métadonnées et noms des exécutables utilisent Macro Studio ; les identifiants de réglages restent stables.
