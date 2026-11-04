import copy
from dataclasses import asdict
from datetime import datetime
import json
import threading
import pytest
from PySide6.QtTest import QTest
from macro_studio.reporting import (ReportConfig, ReportBook, ReportService, contains,
                                    cutoff, load_report_config, report_text)
from macro_studio.run_control import RunControl
from macro_studio.workflow import Workflow, Module, save_workflow, load_workflow
from macro_studio.model import Action
from macro_studio.app import MainWindow
from test_ui import app

NOW = datetime(2026, 11, 2, 18)


def config():
    return ReportConfig(True, ['Ajout de data a relever', 'Erreur'],
                        {'left': -200, 'top': 20, 'width': 300, 'height': 100})


def test_matching_case_accents_spaces_punctuation_and_word_boundaries():
    assert contains('AJOUT de data à\nrelever !', 'ajout de data a relever')
    assert contains('Une erreur.', 'erreur')
    assert not contains('erreurs', 'erreur')
    assert not contains('ajout de mauvaises data a relever', 'ajout de data a relever')


def test_persistent_text_counted_once_and_two_absences_rearm():
    cfg, book = config(), ReportBook()
    for text in ['ERREUR', 'erreur', '', 'erreur', '', '', 'erreur']:
        key = book.sample(cfg, 'Journée', NOW, text)
    assert book.records[key]['counts']['Erreur'] == 2
    assert book.records[key]['counts'][cfg.terms[0]] == 0
    assert book.records[key]['samples'] == 7


def test_ocr_error_does_not_fake_disappearance():
    cfg, book = config(), ReportBook()
    key = book.sample(cfg, 'Test', NOW, 'erreur')
    book.sample(cfg, 'Test', NOW, failed=True)
    book.sample(cfg, 'Test', NOW, failed=True)
    book.sample(cfg, 'Test', NOW, 'erreur')
    assert book.records[key]['counts']['Erreur'] == 1
    assert book.records[key]['errors'] == 2


def test_restart_retains_counts_and_presence():
    cfg, book = config(), ReportBook()
    key = book.sample(cfg, 'Test', NOW, 'erreur')
    restored = ReportBook()
    restored.sample(cfg, 'Test', NOW, 'erreur')
    assert restored.records[key]['counts']['Erreur'] == 1


def test_period_boundary_and_continuous_presence_across_reports():
    cfg, book = config(), ReportBook()
    before = datetime(2026, 11, 2, 18, 59, 59)
    after = datetime(2026, 11, 2, 19)
    first = book.sample(cfg, 'Test', before, 'erreur')
    second = book.sample(cfg, 'Test', after, 'erreur')
    assert first != second
    assert book.records[first]['counts']['Erreur'] == 1
    assert book.records[second]['counts']['Erreur'] == 0
    assert len(book.due(after)) == 1
    assert cutoff(after, '19:00') == datetime(2026, 11, 3, 19)


@pytest.mark.parametrize('changes', [dict(at='25:00'), dict(interval=0), dict(interval=True),
    dict(terms=['']), dict(terms=['été', 'ETE']), dict(region=None), dict(enabled='yes'),
    dict(region={'left': 0, 'top': 0, 'width': 0, 'height': 50}), dict(terms=['x']*31)])
def test_invalid_config_rejected(changes):
    data = asdict(config())
    data.update(changes)
    with pytest.raises(ValueError):
        load_report_config(data)


def test_save_load_and_legacy_workflow(tmp_path):
    workflow = Workflow([Module('Test', [Action.create('wait')])], report=config())
    path = tmp_path/'workflow.json'
    save_workflow(path, workflow)
    assert asdict(load_workflow(path).report) == asdict(workflow.report)
    data = json.loads(path.read_text(encoding='utf-8'))
    del data['report']
    path.write_text(json.dumps(data), encoding='utf-8')
    assert not load_workflow(path).report.enabled


def test_import_retains_current_config_and_copies_on_replacement():
    source = Workflow(report=config())
    target = Workflow()
    target.import_modules(source, replace_empty=True)
    assert target.report == source.report and target.report is not source.report
    preserved = target.report.id
    target.import_modules(Workflow(report=config()))
    assert target.report.id == preserved


class Notifier:
    enabled = True
    url = 'dummy-not-sent'
    def __init__(self):
        self.messages = []
        self.ok = True
    def dispatch(self, url, content, completion=None):
        self.messages.append(content)
        if completion:
            completion(self.ok)


def service():
    now = [NOW]
    notifier = Notifier()
    instance = ReportService(notifier, clock=lambda: now[0], reader=lambda r: 'erreur')
    instance.timer.stop()
    control = RunControl()
    instance.begin(config(), 'Mon workflow', control)
    return instance, notifier, now, control


def test_scheduler_sends_at_19_once_and_remembers_confirmation():
    instance, notifier, now, control = service()
    instance.accept_sample(instance.generation, 'erreur', '', NOW)
    instance.end()
    instance.tick()
    assert not notifier.messages
    now[0] = datetime(2026, 11, 2, 19)
    instance.tick()
    assert len(notifier.messages) == 1 and 'Erreur : 1' in notifier.messages[0]
    instance.tick()
    assert len(notifier.messages) == 1
    restored = ReportService(notifier, clock=lambda: now[0])
    restored.timer.stop()
    restored.tick()
    assert len(notifier.messages) == 1
    instance.close()
    restored.close()


def test_discord_disabled_defers_report_and_failed_send_remains_pending():
    instance, notifier, now, control = service()
    instance.end()
    now[0] = datetime(2026, 11, 2, 19)
    notifier.enabled = False
    instance.tick()
    assert not notifier.messages
    notifier.enabled, notifier.ok = True, False
    instance.tick()
    assert len(notifier.messages) == 1
    assert not next(iter(instance.book.records.values()))['sent']
    instance.tick()
    assert len(notifier.messages) == 1
    notifier.ok = True
    instance.retry.clear()
    instance.tick()
    assert next(iter(instance.book.records.values()))['sent']
    instance.close()


def test_disabled_report_policy_prevents_delivery():
    instance, notifier, now, control = service()
    cfg = copy.deepcopy(instance.config)
    cfg.enabled = False
    instance.book.policy(cfg)
    instance.end()
    now[0] = datetime(2026, 11, 2, 20)
    instance.tick()
    assert not notifier.messages
    instance.close()


def test_paused_and_stale_samples_ignored():
    instance, notifier, now, control = service()
    generation = instance.generation
    control.pause()
    instance.accept_sample(generation, 'erreur', '', NOW)
    assert next(iter(instance.book.records.values()))['samples'] == 0
    control.resume()
    instance.end()
    instance.accept_sample(generation, 'erreur', '', NOW)
    assert next(iter(instance.book.records.values()))['samples'] == 0
    instance.close()


def test_background_ocr_does_not_block_and_due_waits_for_sample():
    instance, notifier, now, control = service()
    entered, release = threading.Event(), threading.Event()
    def reader(region):
        entered.set()
        release.wait(2)
        return 'erreur'
    instance.reader = reader
    control.arm()
    instance.tick()
    assert entered.wait(1) and instance.busy
    now[0] = datetime(2026, 11, 2, 19)
    instance.tick()
    assert not notifier.messages
    release.set()
    for _ in range(100):
        QTest.qWait(10)
        if not instance.busy: break
    instance.end()
    instance.tick()
    assert 'Erreur : 1' in notifier.messages[0]
    instance.close()


def test_long_reports_keep_all_terms_within_discord_limits():
    cfg, book = config(), ReportBook()
    cfg.terms = [f'Terme {i} ' + 'x'*130 for i in range(30)]
    _, row = book.record(cfg, 'Test', NOW)
    chunks = report_text(row)
    assert len(chunks) > 1 and all(len(chunk) <= 1800 for chunk in chunks)
    assert all(term in '\n'.join(chunks) for term in cfg.terms)


def test_panel_updates_config_and_region_without_counting():
    window = MainWindow()
    window.report_panel.terms.setPlainText('Ajout de data a relever\nErreur')
    window.apply_report_region({'left': 1, 'top': 2, 'width': 300, 'height': 100})
    window.report_panel.enabled.setChecked(True)
    assert window.workflow.report.enabled and len(window.workflow.report.terms) == 2
    assert window.dirty and not window.reports.book.records
    window.dirty = False
    window.close()


def test_native_windows_ocr_reads_synthetic_image(tmp_path):
    from PySide6.QtGui import QImage, QPainter, QColor, QFont, QFontDatabase
    from macro_studio.screen_ocr import read_png
    QFontDatabase.addApplicationFont('C:/Windows/Fonts/arial.ttf')
    image = QImage(1000, 160, QImage.Format_RGB32)
    image.fill(QColor('white'))
    painter = QPainter(image)
    painter.setPen(QColor('black'))
    painter.setFont(QFont('Arial', 32))
    painter.drawText(20, 90, 'Ajout de data a relever')
    painter.end()
    path = tmp_path/'ocr.png'
    image.save(str(path))
    assert contains(read_png(path), 'Ajout de data a relever')
