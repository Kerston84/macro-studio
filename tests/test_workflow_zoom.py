import pytest
from macro_studio.app import MainWindow
from test_ui import app


def test_visible_zoom_controls_sync_and_do_not_modify_workflow():
    window = MainWindow()
    panel = window.workflow_panel
    panel.zoom_in.click()
    assert panel.canvas.transform().m11() == pytest.approx(1.15)
    assert panel.zoom_label.text() == '115 %'
    panel.zoom_out.click()
    assert panel.canvas.transform().m11() == pytest.approx(1)
    panel.zoom_slider.setValue(175)
    assert panel.canvas.transform().m11() == pytest.approx(1.75)
    panel.zoom_reset.click()
    assert panel.zoom_slider.value() == 100
    assert not window.dirty
    window.close()


def test_zoom_bounds_and_fit_below_minimum():
    window = MainWindow()
    panel = window.workflow_panel
    panel.zoom_slider.setValue(300)
    assert not panel.zoom_in.isEnabled()
    panel.canvas.zoom_by(1.15)
    assert panel.canvas.transform().m11() == pytest.approx(3)
    panel.zoom_slider.setValue(10)
    assert not panel.zoom_out.isEnabled()
    panel.canvas.scale(.01, .01)
    before = panel.canvas.transform().m11()
    panel.canvas.zoom_by(1 / 1.15)
    assert panel.canvas.transform().m11() == before
    panel.canvas.zoom_by(1.15)
    assert panel.canvas.transform().m11() == pytest.approx(.1)
    window.close()


def test_fit_updates_readout_and_manual_zoom_keeps_center():
    window = MainWindow()
    window.show()
    window.tabs.setCurrentIndex(1)
    app.processEvents()
    panel = window.workflow_panel
    panel.fit()
    assert panel.zoom_label.text() == f'{panel.canvas.transform().m11() * 100:.0f} %'
    center = panel.canvas.mapToScene(panel.canvas.viewport().rect().center())
    panel.canvas.zoom_by(1.15)
    after = panel.canvas.mapToScene(panel.canvas.viewport().rect().center())
    assert abs(center.x() - after.x()) < 4 and abs(center.y() - after.y()) < 4
    window.close()
