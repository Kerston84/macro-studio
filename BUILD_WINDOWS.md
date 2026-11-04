# Construire et distribuer Macro Studio

La distribution Windows 64 bits comprend un installateur `.exe`, une archive portable contenant `MacroStudio.exe`, les empreintes SHA-256 et un rapport de diagnostic. Python et les bibliothèques sont inclus : aucun environnement Python n’est nécessaire chez l’utilisateur.

## Prérequis de compilation

- Windows 10 ou 11, 64 bits ; Python 3.12 64 bits est utilisé pour cette livraison.
- Les dépendances de l’application et des tests dans un environnement virtuel.
- PyInstaller 6.22.3 et Pillow 12.3.0 (`pip install -e ".[test,build]"`).
- [Inno Setup](https://jrsoftware.org/isdl.php), version 6.6+ ou 7. La livraison a été compilée avec Inno Setup 7.1.1 x64, téléchargé sur le site officiel et dont la signature de l’éditeur Pyrsys B.V. a été vérifiée.

Depuis le dossier du projet :

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-build.txt
.\.venv\Scripts\python.exe tools\build_windows.py --iscc "C:\chemin\vers\Inno Setup\ISCC.exe"
```

Le script exécute les tests, génère l’icône et les informations de version, compile avec PyInstaller en mode dossier, ajoute les licences, lance le diagnostic sur l’exécutable puis produit l’installateur et l’archive portable. Le diagnostic retire les chemins Python/Qt externes et limite `PATH` aux dossiers système Windows. L’option `--skip-tests` permet de réutiliser une suite déjà vérifiée ; le diagnostic de l’exécutable reste obligatoire.

La compilation nettoie aussi `PATH` pour ne pas embarquer les DLL d’autres outils installés. Qt utilise la façade ICU intégrée à Windows ; une DLL ICU externe peut exporter des symboles différents et empêcher son chargement. Les bibliothèques Visual C++ fournies avec Qt sont alignées dans le paquet. L’option `--reuse-bundle` sert uniquement à reconditionner un dossier déjà compilé lorsque les sources n’ont pas changé ; le diagnostic et le contrôle de version restent exécutés.

Si une stratégie de contrôle d’application Windows refuse explicitement l’exécution (erreur 4551), `--runtime-check-blocked` permet uniquement de préparer les fichiers sans les lancer. Cette option ne modifie aucune protection et écrit un diagnostic bloqué ainsi qu’un fichier `LANCEMENT-NON-VALIDE.txt`. Une telle livraison ne doit pas être présentée comme validée en exécution ou en installation.

La sortie par défaut est un dossier `MacroStudio-release-<version>` à côté du projet. Pour choisir une autre destination : `--output "C:\chemin\livraison"`.

## Choix de distribution

L’application utilise un dossier PyInstaller plutôt qu’un exécutable qui extrait toutes ses dépendances à chaque lancement. L’installateur est un fichier unique téléchargeable ; il place l’exécutable et ses bibliothèques dans `%LOCALAPPDATA%\Programs\Macro Studio`. Aucune élévation administrateur n’est demandée. Le menu Démarrer reçoit un raccourci et le Bureau est optionnel. La version portable doit être entièrement extraite et conserver son dossier `_internal`.

Un ancien dossier de workflows existant est réutilisé lors des mises à jour. Les nouveaux workflows sont proposés dans le dossier Documents Windows, sous `Macro Studio\Workflows`. Les documents existants ne sont ni déplacés ni inclus dans les binaires. L’historique et les réglages existants restent accessibles via le même profil Windows. Le mode portable utilise également ce profil : il ne transporte pas les secrets Discord avec le dossier du programme.

L’identifiant de l’installateur est stable afin de permettre les mises à jour. La désinstallation ne supprime ni les workflows, ni les réglages du profil, ni les compteurs. Le programme signale au système quand il est ouvert pour éviter de le remplacer pendant son exécution. Fermez et sauvegardez l’application avant de mettre à jour.

## Diagnostic sans interaction sur le Bureau

```powershell
& ".\MacroStudio\MacroStudio.exe" --self-test "$env:TEMP\macro-studio-diagnostic.json"
```

Ce diagnostic construit l’interface hors écran, utilise des réglages et fichiers temporaires, teste les icônes, la sauvegarde de deux modules, le menu d’accueil, les dépendances natives, DPAPI et l’OCR Windows sur une image synthétique. Il ne capture pas l’écran personnel, n’envoie pas de touches/clics et ne contacte pas Discord. Il quitte avec le code 0 si tout est validé, 1 sinon.

En cas d’erreur de démarrage normale, le détail est enregistré dans `%LOCALAPPDATA%\WindowsMacroStudio\Logs\startup-error.log`.

Le script `tools\smoke_installer.py` peut vérifier l’installateur dans un nouveau dossier de test, puis le désinstaller. Il refuse de s’exécuter si une installation normale existe déjà pour ce compte, afin de ne pas la remplacer. Exemple : `python tools\smoke_installer.py "C:\livraison\MacroStudio-Setup-0.18.0-x64.exe" "C:\travail\nouveau-dossier-validation"`. Ce test installe temporairement l’application sur le compte Windows, avec sa clé de désinstallation, sans raccourcis et sans modifier les préférences existantes.

## Avant une diffusion publique

Cette première livraison n’a pas de signature de code. Une signature Authenticode avec un certificat appartenant à l’éditeur et des essais sur d’autres PC Windows restent à prévoir avant une diffusion large. Aucun certificat ni identité d’éditeur n’est inventé. Windows peut afficher un avertissement de réputation pour un nouveau binaire non signé.

Les licences des dépendances sont conservées dans `Licences` et les DLL Qt restent des bibliothèques partagées. Conservez ces notices lors de la redistribution. La langue OCR de Windows doit être installée sur le PC destinataire pour utiliser le suivi de texte. La vérification sur cette machine ne remplace pas une validation sur une machine Windows propre.
