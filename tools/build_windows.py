"""Build the standalone folder, portable ZIP and per-user Windows installer."""
import argparse
import hashlib
from importlib import metadata
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tomllib
from zipfile import ZipFile, ZIP_DEFLATED

ROOT = Path(__file__).resolve().parents[1]
VERSION = tomllib.loads((ROOT / 'pyproject.toml').read_text(encoding='utf-8'))['project']['version']


def icon():
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from PySide6.QtCore import QByteArray, QBuffer, QIODevice
    from PySide6.QtGui import QGuiApplication, QImage, QPainter
    from PySide6.QtSvg import QSvgRenderer
    from PIL import Image
    app = QGuiApplication.instance() or QGuiApplication([])
    image = QImage(256, 256, QImage.Format_ARGB32)
    image.fill(0)
    painter = QPainter(image)
    QSvgRenderer(str(ROOT / 'macro_studio/icons/app.svg')).render(painter)
    painter.end()
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.WriteOnly)
    image.save(buffer, 'PNG')
    target = ROOT / 'macro_studio/icons/app.ico'
    Image.open(io.BytesIO(bytes(data))).save(target, sizes=[(s, s) for s in (16, 24, 32, 48, 64, 128, 256)])
    return target


def notices(folder):
    folder.mkdir(parents=True, exist_ok=True)
    lines = ['Macro Studio — bibliothèques distribuées', '',
             'Qt/PySide6 sont chargés comme bibliothèques partagées. Leurs licences et les autres notices sont conservées ci-dessous.',
             'Sources Qt : https://download.qt.io/archive/qt/',
             'Sources PySide6/Shiboken : https://download.qt.io/official_releases/QtForPython/', '']
    for name in ('PySide6', 'PySide6_Essentials', 'shiboken6', 'numpy', 'opencv-python-headless', 'mss', 'pynput', 'six', 'Pillow', 'pyinstaller',
                 'discord.py', 'aiohttp', 'aiohappyeyeballs', 'aiosignal', 'attrs', 'frozenlist',
                 'multidict', 'propcache', 'typing_extensions', 'yarl', 'idna'):
        distribution = metadata.distribution(name)
        lines.append(f'{name} {distribution.version}')
        lines.extend(distribution.metadata.get_all('Project-URL', []))
        for entry in distribution.files or []:
            if ('licenses' in [p.lower() for p in entry.parts] or entry.name.upper().startswith(('LICENSE', 'COPYING', 'NOTICE'))):
                source = Path(distribution.locate_file(entry)).resolve()
                if source.is_file():
                    target = folder / name / str(entry).replace('..', '_')
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, target)
        lines.append('')
    python_license = Path(sys.base_prefix) / 'LICENSE.txt'
    if python_license.exists():
        shutil.copy2(python_license, folder / 'PYTHON-LICENSE.txt')
    (folder / 'LISEZ-MOI.txt').write_text('\n'.join(lines), encoding='utf-8')
    shutil.copytree(ROOT / 'packaging/licences', folder / 'Qt-license-texts', dirs_exist_ok=True)


def version_file(path):
    from PyInstaller.utils.win32.versioninfo import VSVersionInfo, FixedFileInfo, StringFileInfo, StringTable, StringStruct, VarFileInfo, VarStruct
    version = tuple(map(int, VERSION.split('.'))) + (0,)
    info = VSVersionInfo(ffi=FixedFileInfo(filevers=version, prodvers=version, mask=0x3f, flags=0, OS=0x40004, fileType=1, subtype=0, date=(0, 0)),
        kids=[StringFileInfo([StringTable('040c04b0', [StringStruct(k, v) for k, v in {
            'CompanyName': 'Macro Studio', 'FileDescription': 'Macro Studio',
            'FileVersion': VERSION, 'InternalName': 'MacroStudio',
            'OriginalFilename': 'MacroStudio.exe', 'ProductName': 'Macro Studio',
            'ProductVersion': VERSION}.items()])]), VarFileInfo([VarStruct('Translation', [1036, 1200])])])
    path.write_text(str(info), encoding='utf-8')


def run(command, **kwargs):
    subprocess.run([str(c) for c in command], check=True, cwd=ROOT, **kwargs)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--iscc', type=Path, help='Chemin vers ISCC.exe (Inno Setup 6.6+ ou 7)')
    parser.add_argument('--output', type=Path, default=ROOT.parent / f'MacroStudio-release-{VERSION}')
    parser.add_argument('--skip-tests', action='store_true', help='Réutiliser une suite déjà vérifiée ; diagnostic du .exe toujours effectué')
    parser.add_argument('--reuse-bundle', action='store_true', help='Reconditionner le dossier déjà compilé, sans recompilation (sources inchangées uniquement)')
    parser.add_argument('--runtime-check-blocked', action='store_true', help='Produire les fichiers sans les lancer après un blocage de sécurité Windows ; diagnostic explicitement non validé')
    args = parser.parse_args()
    compiler = args.iscc or shutil.which('ISCC.exe')
    if not compiler or not Path(compiler).is_file():
        parser.error('Installez Inno Setup puis indiquez --iscc ".../ISCC.exe".')
    if sys.platform != 'win32' or sys.maxsize <= 2**32:
        parser.error('La compilation nécessite Python 64 bits sur Windows.')
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    stage = ROOT / 'build' / 'windows'
    stage.mkdir(parents=True, exist_ok=True)
    if not args.skip_tests:
        run([sys.executable, '-m', 'pytest', '-q'])
    app_icon = icon()
    versions = stage / 'version-info.txt'
    version_file(versions)
    licenses = stage / 'Licences'
    notices(licenses)
    command = [sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', '--onedir', '--windowed',
        '--name', 'MacroStudio', '--icon', app_icon, '--version-file', versions,
        '--distpath', stage / 'dist', '--workpath', stage / 'pyinstaller', '--specpath', stage,
        '--paths', ROOT, '--add-data', f'{ROOT / "macro_studio/icons"};macro_studio/icons',
        '--hidden-import', 'pynput.keyboard._win32', '--hidden-import', 'pynput.mouse._win32',
        '--hidden-import', 'pynput._util.win32', '--hidden-import', 'mss.windows',
        '--hidden-import', 'PySide6.QtSvg', '--noupx']
    for module in ('pytest', 'tkinter', 'PySide6.QtWebEngineCore', 'PySide6.QtWebEngineWidgets',
                   'PySide6.QtQml', 'PySide6.QtQuick', 'PySide6.QtMultimedia', 'PySide6.QtPdf', 'PySide6.QtPdfWidgets'):
        command += ['--exclude-module', module]
    command.append(ROOT / 'run_app.py')
    bundle = stage / 'dist/MacroStudio'
    if not args.reuse_bundle:
        build_environment = dict(os.environ)
        # Avoid collecting unrelated DLLs from tools such as Poppler on PATH.
        build_environment['PATH'] = os.pathsep.join([str(Path(sys.executable).parent), sys.base_prefix,
            str(Path(os.environ['SystemRoot']) / 'System32'), os.environ['SystemRoot']])
        run(command, env=build_environment)
    if not (bundle / 'MacroStudio.exe').is_file():
        raise RuntimeError('Dossier compilé introuvable ; lancez une compilation complète.')
    # Qt uses the ICU facade provided by Windows 10/11. A foreign ICU with
    # version-suffixed exports shadows it and prevents QtCore from loading.
    for filename in ('icuuc.dll', 'icudt78.dll'):
        foreign_icu = bundle / '_internal' / filename
        if foreign_icu.is_file():
            foreign_icu.unlink()
    # Python and Qt can ship different VC++ runtimes. The process loads the
    # root copy first, so align it with the newer redistributable shipped by Qt.
    import PySide6
    qt_folder = Path(PySide6.__file__).parent
    for filename in ('vcruntime140.dll', 'vcruntime140_1.dll', 'msvcp140.dll', 'msvcp140_1.dll',
                     'msvcp140_2.dll', 'msvcp140_codecvt_ids.dll', 'concrt140.dll'):
        source = qt_folder / filename
        if source.is_file():
            shutil.copy2(source, bundle / '_internal' / filename)
    shutil.copytree(licenses, bundle / 'Licences', dirs_exist_ok=True)
    shutil.copy2(ROOT / 'packaging/LISEZ-MOI.txt', bundle / 'LISEZ-MOI.txt')
    shutil.copy2(ROOT / 'DISCORD.md', bundle / 'DISCORD.md')
    shutil.copy2(ROOT / 'LICENSE', bundle / 'LICENSE')
    diagnostic = output / 'diagnostic-executable.json'
    environment = dict(os.environ)
    for variable in ('PYTHONHOME', 'PYTHONPATH', 'QT_PLUGIN_PATH', 'QT_QPA_PLATFORM_PLUGIN_PATH'):
        environment.pop(variable, None)
    environment['PATH'] = os.pathsep.join([str(Path(os.environ['SystemRoot']) / 'System32'), os.environ['SystemRoot']])
    if args.runtime_check_blocked:
        diagnostic.write_text(json.dumps({'ok': False, 'version': VERSION, 'checks': [],
            'blocked': True, 'reason': 'Lancement bloqué par le contrôle d’application Windows (erreur 4551). Aucun contournement effectué. Exécutable et installateur non validés en exécution.'},
            ensure_ascii=False, indent=2), encoding='utf-8')
        (output / 'LANCEMENT-NON-VALIDE.txt').write_text(
            'Les tests du code source passent, mais Windows bloque le lancement du nouvel exécutable (erreur 4551).\n'
            'Cette livraison est compilée, sans validation de lancement ni de cycle d’installation.\n'
            'Aucune protection Windows n’a été désactivée. Une signature reconnue ou une analyse de la stratégie par l’administrateur peut être nécessaire.\n', encoding='utf-8')
    else:
        run([bundle / 'MacroStudio.exe', '--self-test', diagnostic], env=environment, timeout=90)
        report = json.loads(diagnostic.read_text(encoding='utf-8'))
        if not report['ok'] or report.get('version') != VERSION:
            raise RuntimeError('Le diagnostic autonome a échoué.')
    run([compiler, f'/DAppVersion={VERSION}', f'/DBundleDir={bundle}', f'/DOutputDir={output}',
         f'/DAppIcon={app_icon}', ROOT / 'packaging/installer.iss'])
    archive = output / f'MacroStudio-Portable-{VERSION}-x64.zip'
    with ZipFile(archive, 'w', ZIP_DEFLATED) as zipped:
        for path in bundle.rglob('*'):
            if path.is_file():
                zipped.write(path, Path('MacroStudio') / path.relative_to(bundle))
    shutil.copy2(ROOT / 'packaging/LISEZ-MOI.txt', output / 'LISEZ-MOI.txt')
    shutil.copy2(ROOT / 'DISCORD.md', output / 'DISCORD.md')
    checksums = []
    for path in sorted(output.iterdir()):
        if path.suffix in ('.exe', '.zip'):
            checksums.append(hashlib.file_digest(path.open('rb'), 'sha256').hexdigest() + '  ' + path.name)
    (output / 'SHA256SUMS.txt').write_text('\n'.join(checksums) + '\n', encoding='ascii')
    print(f'Distribution prête : {output}', flush=True)


if __name__ == '__main__':
    main()
