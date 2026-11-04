"""Validate this installer in an explicit disposable folder, then uninstall it."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import winreg

UNINSTALL_KEY = r'Software\Microsoft\Windows\CurrentVersion\Uninstall\{462CFA5D-1847-4CE8-BBD8-50DDFD79D582}_is1'


def preferences_digest():
    values = []
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Software\WindowsMacroStudio\Documents') as key:
            index = 0
            while True:
                try:
                    values.append(winreg.EnumValue(key, index))
                    index += 1
                except OSError:
                    break
    except FileNotFoundError:
        pass
    return hashlib.sha256(repr(sorted(values)).encode()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('installer', type=Path)
    parser.add_argument('sandbox', type=Path)
    args = parser.parse_args()
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY):
            parser.error('Une installation existe déjà : test refusé pour ne pas la remplacer.')
    except FileNotFoundError:
        pass
    installer, sandbox = args.installer.resolve(), args.sandbox.resolve()
    if not installer.is_file() or sandbox.exists():
        parser.error('Indiquez un installateur existant et un nouveau dossier de test vide.')
    sandbox.mkdir(parents=True)
    target = (sandbox / 'application').resolve()
    assert target.is_relative_to(sandbox)
    before = preferences_digest()
    command = [str(installer), '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/SP-',
               '/NOICONS', '/TASKS=', f'/DIR={target}']
    subprocess.run(command + [f'/LOG={sandbox / "installation.log"}'], check=True, timeout=180)
    assert (target / 'WindowsMacroStudio.exe').is_file()
    environment = dict(os.environ)
    for variable in ('PYTHONHOME', 'PYTHONPATH', 'QT_PLUGIN_PATH', 'QT_QPA_PLATFORM_PLUGIN_PATH'):
        environment.pop(variable, None)
    environment['PATH'] = os.pathsep.join([str(Path(os.environ['SystemRoot']) / 'System32'), os.environ['SystemRoot']])
    subprocess.run([str(target / 'WindowsMacroStudio.exe'), '--self-test', str(sandbox / 'diagnostic-installe.json')],
                   check=True, timeout=90, env=environment)
    assert json.loads((sandbox / 'diagnostic-installe.json').read_text(encoding='utf-8'))['ok']
    subprocess.run(command + [f'/LOG={sandbox / "mise-a-jour.log"}'], check=True, timeout=180)
    assert (target / 'WindowsMacroStudio.exe').is_file()
    assert preferences_digest() == before
    uninstaller = (target / 'unins000.exe').resolve()
    assert uninstaller.is_relative_to(sandbox) and uninstaller.is_file()
    subprocess.run([str(uninstaller), '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART',
                    f'/LOG={sandbox / "desinstallation.log"}'], check=True, timeout=180)
    assert not (target / 'WindowsMacroStudio.exe').exists()
    assert preferences_digest() == before
    result = {'ok': True, 'checks': ['installation silencieuse', 'diagnostic du programme installé',
               'mise à jour sur place', 'désinstallation', 'préférences existantes conservées']}
    (sandbox / 'validation-installateur.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print('Installation, mise à jour et désinstallation validées ; préférences conservées.')


if __name__ == '__main__':
    main()
