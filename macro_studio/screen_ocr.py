"""Local Windows OCR, isolated in a hidden bounded PowerShell process."""
import base64
import os
from pathlib import Path
import subprocess
import tempfile

SCRIPT = r'''
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null = [Windows.Storage.StorageFile, Windows.Storage, ContentType=WindowsRuntime]
$null = [Windows.Storage.FileAccessMode, Windows.Storage, ContentType=WindowsRuntime]
$null = [Windows.Storage.Streams.IRandomAccessStream, Windows.Storage.Streams, ContentType=WindowsRuntime]
$null = [Windows.Graphics.Imaging.BitmapDecoder, Windows.Graphics.Imaging, ContentType=WindowsRuntime]
$null = [Windows.Graphics.Imaging.SoftwareBitmap, Windows.Graphics.Imaging, ContentType=WindowsRuntime]
$null = [Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType=WindowsRuntime]
$null = [Windows.Media.Ocr.OcrResult, Windows.Foundation, ContentType=WindowsRuntime]
$asTask = [System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object { $_.Name -eq 'AsTask' -and $_.IsGenericMethod -and $_.GetGenericArguments().Count -eq 1 -and $_.GetParameters().Count -eq 1 } | Select-Object -First 1
function Await($operation, $resultType) {
    $task = $asTask.MakeGenericMethod($resultType).Invoke($null, @($operation))
    $task.GetAwaiter().GetResult()
}
$engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()
if ($null -eq $engine) { throw 'OCR Windows indisponible : installez une langue OCR dans les paramètres Windows.' }
$file = Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync($env:MACRO_OCR_IMAGE)) ([Windows.Storage.StorageFile])
$stream = Await ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
try {
    $decoder = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
    $bitmap = Await ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
    try {
        $result = Await ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])
        [Console]::Write([Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($result.Text)))
    } finally { $bitmap.Dispose() }
} finally { $stream.Dispose() }
'''


def read_png(path):
    env = dict(os.environ, MACRO_OCR_IMAGE=str(Path(path).resolve()))
    powershell = str(Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32/WindowsPowerShell/v1.0/powershell.exe')
    try:
        result = subprocess.run([powershell, '-NoProfile', '-NonInteractive', '-EncodedCommand',
            base64.b64encode(SCRIPT.encode('utf-16-le')).decode('ascii')], env=env,
            capture_output=True, timeout=20, creationflags=subprocess.CREATE_NO_WINDOW)
    except (OSError, subprocess.TimeoutExpired):
        raise ValueError('Lecture OCR Windows indisponible ou trop longue.') from None
    if result.returncode:
        raise ValueError('OCR Windows indisponible. Vérifiez les langues OCR installées dans les paramètres Windows.')
    try:
        return base64.b64decode(result.stdout.strip(), validate=True).decode('utf-8')
    except (ValueError, UnicodeError):
        raise ValueError('Réponse OCR Windows illisible.') from None


def read_region(region):
    import cv2
    from .vision import capture_region
    image, _, _ = capture_region(region)
    height, width = image.shape[:2]
    if max(height, width) > 2400:
        factor = 2400 / max(height, width)
        image = cv2.resize(image, None, fx=factor, fy=factor)
    elif height < 600 and width < 1200:
        image = cv2.resize(image, None, fx=2, fy=2)
    with tempfile.TemporaryDirectory(prefix='macro-ocr-') as folder:
        path = Path(folder) / 'zone.png'
        path.write_bytes(cv2.imencode('.png', image)[1].tobytes())
        return read_png(path)
