"""Daily OCR appearance counters and local, persistent report delivery."""
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
import copy
import hashlib
import json
import re
import threading
import time
import unicodedata
from uuid import uuid4
from PySide6.QtCore import QObject, QTimer, Signal
from . import launcher


def normalized(text):
    text = ''.join(c for c in unicodedata.normalize('NFKD', text.casefold()) if not unicodedata.combining(c))
    return ' '.join(re.findall(r'\w+', text, re.UNICODE))


def contains(text, term):
    return (' ' + normalized(term) + ' ') in (' ' + normalized(text) + ' ')


@dataclass
class ReportConfig:
    enabled: bool = False
    terms: list = field(default_factory=list)
    region: dict | None = None
    at: str = '19:00'
    interval: int = 5
    id: str = field(default_factory=lambda: uuid4().hex)

    def validate(self):
        if type(self.enabled) is not bool or not isinstance(self.id, str) or not 1 <= len(self.id) <= 128:
            raise ValueError('Configuration du compte rendu invalide.')
        if not isinstance(self.at, str) or not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', self.at):
            raise ValueError('Heure du compte rendu invalide.')
        if type(self.interval) is not int or not 1 <= self.interval <= 300:
            raise ValueError('Intervalle OCR : entre 1 et 300 secondes.')
        if not isinstance(self.terms, list) or len(self.terms) > 30:
            raise ValueError('Indiquez au maximum 30 termes.')
        if any(not isinstance(t, str) or not normalized(t) or len(t) > 150 for t in self.terms):
            raise ValueError('Chaque terme doit contenir entre 1 et 150 caractères utiles.')
        if len({normalized(t) for t in self.terms}) != len(self.terms):
            raise ValueError('Retirez les termes en double.')
        if self.region is not None:
            if (not isinstance(self.region, dict) or set(self.region) != {'left', 'top', 'width', 'height'}
                or any(type(v) is not int for v in self.region.values())
                or not 20 <= self.region['width'] <= 10000 or not 20 <= self.region['height'] <= 10000):
                raise ValueError('Zone du compte rendu invalide.')
        if self.enabled and (not self.terms or self.region is None):
            raise ValueError('Choisissez une zone et au moins un terme pour activer le compte rendu.')


def load_report_config(data):
    if data is None:
        return ReportConfig()
    if not isinstance(data, dict) or set(data) - set(ReportConfig.__dataclass_fields__):
        raise ValueError('Compte rendu invalide.')
    config = ReportConfig(**data)
    config.validate()
    return config


def cutoff(now, at):
    hour, minute = map(int, at.split(':'))
    end = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    return end if now < end else end + timedelta(days=1)


class ReportBook:
    def __init__(self, settings=None):
        self.settings = settings if settings is not None else launcher.default_settings()
        self.records, self.states = {}, {}
        self.load_error = ''
        try:
            data = json.loads(self.settings.value('reports/ledger', '{}'))
            self.records = data.get('records', {})
            self.states = data.get('states', {})
            if not isinstance(self.records, dict) or not isinstance(self.states, dict):
                raise ValueError()
            for row in self.records.values():
                datetime.fromisoformat(row['due'])
                assert isinstance(row['counts'], dict) and type(row['enabled']) is bool and type(row['sent']) is bool
                assert all(isinstance(k, str) and type(v) is int and v >= 0 for k, v in row['counts'].items())
                assert all(type(row[k]) is int and row[k] >= 0 for k in ('samples', 'errors'))
                assert all(isinstance(row[k], str) for k in ('config_id', 'document', 'started'))
            for state in self.states.values():
                assert type(state['present']) is bool and type(state['misses']) is int
        except (ValueError, TypeError, KeyError, AssertionError, AttributeError):
            self.records, self.states = {}, {}
            self.load_error = 'Historique des comptes rendus illisible : aucun ancien compteur n’a pu être restauré.'

    def save(self):
        self.settings.setValue('reports/ledger', json.dumps({'records': self.records, 'states': self.states}, ensure_ascii=False))
        self.settings.sync()
        if self.settings.status() != self.settings.Status.NoError:
            raise ValueError('Impossible de sauvegarder les compteurs du compte rendu.')

    def record(self, config, document, now):
        due = cutoff(now, config.at).isoformat(timespec='minutes')
        signature = hashlib.sha256(json.dumps([config.region, config.terms], sort_keys=True).encode()).hexdigest()[:16]
        key = f'{config.id}:{signature}:{due}'
        if key not in self.records:
            self.records[key] = {'config_id': config.id, 'document': document, 'due': due,
                'started': now.isoformat(timespec='seconds'), 'counts': {t: 0 for t in config.terms},
                'samples': 0, 'errors': 0, 'sent': False, 'enabled': True}
        return key, self.records[key]

    def sample(self, config, document, now, text=None, failed=False):
        key, row = self.record(config, document, now)
        if failed:
            row['errors'] += 1
        else:
            row['samples'] += 1
            for term in config.terms:
                state_key = f'{config.id}:{config.region}:{normalized(term)}'
                state = self.states.setdefault(state_key, {'present': False, 'misses': 0})
                if contains(text or '', term):
                    if not state['present']:
                        row['counts'][term] += 1
                    state.update(present=True, misses=0)
                else:
                    state['misses'] = min(2, state['misses'] + 1)
                    if state['misses'] >= 2:
                        state['present'] = False
        self.save()
        return key

    def policy(self, config):
        for row in self.records.values():
            if row['config_id'] == config.id:
                row['enabled'] = config.enabled
        self.save()

    def due(self, now):
        return [(key, row) for key, row in self.records.items()
                if row['enabled'] and not row['sent'] and datetime.fromisoformat(row['due']) <= now]


def report_text(row):
    lines = [f'📊 Compte rendu — {row["document"][:120]}',
             f'Du {row["started"]} au {row["due"]} (heure locale du PC)',
             'Apparitions distinctes observées dans la zone :']
    lines.extend(f'• {term[:150]} : {count}' for term, count in row['counts'].items())
    lines.append(f'Lectures réussies : {row["samples"]} · erreurs OCR : {row["errors"]}')
    lines.append('Texte continu compté une fois ; disparition confirmée sur deux lectures. Suivi seulement pendant l’exécution, hors pauses.')
    # Chunk at lines so every configured term is retained within Discord limits.
    chunks, current = [], ''
    for line in lines:
        if len(current) + len(line) + 1 > 1800:
            chunks.append(current)
            current = '📊 Compte rendu (suite)\n'
        current += line + '\n'
    return chunks + [current]


class ReportService(QObject):
    changed = Signal()
    message = Signal(str)
    sample_done = Signal(int, str, str, object)
    delivered = Signal(str, bool)
    preview_done = Signal(str, str)

    def __init__(self, notifier, parent=None, reader=None, clock=datetime.now):
        super().__init__(parent)
        from .screen_ocr import read_region
        self.notifier, self.reader, self.clock = notifier, reader or read_region, clock
        self.book = ReportBook()
        self.config, self.document, self.control = None, '', None
        self.generation, self.busy, self.next_scan = 0, False, 0
        self.inflight, self.retry = set(), {}
        self.sample_done.connect(self.accept_sample)
        self.delivered.connect(self.accept_delivery)
        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self.tick)
        self.timer.start()

    def begin(self, config, document, control):
        self.end()
        if not config.enabled:
            return
        config.validate()
        self.config, self.document, self.control = copy.deepcopy(config), document, control
        self.book.policy(config)
        self.book.record(config, document, self.clock())
        self.book.save()
        self.changed.emit()

    def end(self):
        self.generation += 1
        self.config, self.control = None, None
        self.next_scan = 0

    def tick(self):
        now = self.clock()
        if self.notifier.enabled and not self.busy:
            for key, row in self.book.due(now):
                if key in self.inflight or time.monotonic() < self.retry.get(key, 0):
                    continue
                self.inflight.add(key)
                # One summary may span several messages; confirm all before marking delivered.
                chunks = report_text(row)
                def send_next(index=0, key=key, chunks=chunks):
                    if not self.notifier.enabled:
                        self.delivered.emit(key, False)
                        return
                    def completed(ok):
                        if not ok or index + 1 == len(chunks):
                            self.delivered.emit(key, ok)
                        else:
                            send_next(index + 1)
                    self.notifier.dispatch(self.notifier.url, chunks[index], completion=completed)
                send_next()
                break  # Do not flood Discord with restored reports.
        if (not self.config or self.busy or not self.control.armed or self.control.paused
            or self.control.is_set() or self.control.safety_suspended or time.monotonic() < self.next_scan):
            return
        self.busy = True
        generation, region, sampled_at = self.generation, dict(self.config.region), now
        def read():
            text, problem = '', ''
            try:
                text = self.reader(region)
            except Exception:
                problem = 'Lecture OCR impossible : vérifiez la zone et les langues OCR Windows.'
            try:
                self.sample_done.emit(generation, text, problem, sampled_at)
            except RuntimeError:
                pass
        threading.Thread(target=read, daemon=True, name='report-ocr').start()

    def accept_sample(self, generation, text, problem, sampled_at):
        self.busy = False
        if generation != self.generation or not self.config or self.control.paused or self.control.is_set():
            return
        self.next_scan = time.monotonic() + self.config.interval
        try:
            self.book.sample(self.config, self.document, sampled_at, text, bool(problem))
            if problem:
                self.message.emit(problem)
        except ValueError as exc:
            self.message.emit(str(exc))
        self.changed.emit()

    def accept_delivery(self, key, ok):
        self.inflight.discard(key)
        if ok:
            self.book.records[key]['sent'] = True
            try:
                self.book.save()
            except ValueError as exc:
                self.message.emit(str(exc))
        else:
            self.retry[key] = time.monotonic() + 60
        self.changed.emit()

    def close(self):
        self.timer.stop()
        self.end()

    def preview(self, region):
        def read():
            try:
                text, problem = self.reader(region), ''
            except Exception:
                text, problem = '', 'OCR impossible : vérifiez la zone et les langues OCR Windows.'
            try:
                self.preview_done.emit(text, problem)
            except RuntimeError:
                pass
        threading.Thread(target=read, daemon=True, name='ocr-preview').start()
