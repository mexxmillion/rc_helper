# -*- coding: utf-8 -*-
# Full script updated with:
# - LINEUP_CAM_ALT:
#     * After building LINEUP_CAM, we DUPLICATE its animation (transform + shape)
#       onto LINEUP_CAM_ALT using copyKey/pasteKey.
#     * Then, for each frame in the lineup range, we:
#           - Query LINEUP_CAM vertical + horizontal film aperture
#           - Compute original aspect = hfa / vfa
#           - Compute scaleFactor = aspect_alt / original_aspect
#           - Set hfa_alt = hfa * scaleFactor, vfa_alt = vfa
#           - Key horizontalFilmAperture + verticalFilmAperture on ALT
#       This guarantees ALT is a frame-by-frame duplicate of LINEUP_CAM, with only
#       the horizontal aperture adjusted to the new aspect.
# - Scene Export:
#     * New /scene_export folder.
#     * New checkboxes:
#           - "Scene FBX"  (full-scene FBX export)
#           - "Scene ABC"  (full-scene Alembic export)
#     * Scene exports respect the same frame range as camera exports and go to
#       /scene_export. Camera export and scene export can be used independently
#       or together.
# - Previous behaviour kept:
#     * ImagePlanes only visible through their own camera (displayOnlyIfCurrent=1).
#     * Only LINEUP_CAM(+ALT) renderable; others set non-renderable.
#     * Render resolution and frame range taken from lineup images.
#     * Nuke template is embedded and written procedurally (no external nk dependency).
#     * oiiotool runs via hidden subprocess (no focus-stealing consoles).

from PySide2 import QtCore, QtGui, QtWidgets
from PySide2.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton,
    QListWidget, QListWidgetItem, QFileDialog, QLineEdit, QSpinBox, QDoubleSpinBox,
    QMessageBox, QFrame, QDialog, QTableWidget, QTableWidgetItem, QHeaderView,
    QGroupBox, QTextEdit, QComboBox, QProgressDialog, QCheckBox
)
import os
import inspect
import sys
import shutil
import re
import json
import datetime
import getpass
import subprocess
import filecmp
from pathlib import Path
import maya.cmds as cmds
import maya.mel as mel

# Scanline pipeline API
import scl.commonAPI.commonAPI as cAPI

# ----------------------------- Constants -----------------------------
DEFAULT_START_FRAME = 1001
DEFAULT_OIIOTOOL = r'//s2/exchange/software/tools/OpenImageIO/2.3.16/oiiotool.exe'.replace('\\', '/')

PIPELINE_ROOT_TEMPLATE = r'\\inferno2\projects\{project}\lineup\{asset}'.replace('\\', '/')

# Assume shared scripts live in this root
CAS_SCRIPTS_ROOT = r'//inferno2/projects/common/home/quw/cas_scripts'.replace('\\', '/')

def _script_dir():
    # Kept for any relative needs; not used for cam_order path anymore
    try:
        return Path(__file__).resolve().parent.as_posix()
    except NameError:
        pass
    try:
        return Path(inspect.getfile(sys.modules[__name__])).resolve().parent.as_posix()
    except Exception:
        pass
    try:
        return Path(sys.argv[0]).resolve().parent.as_posix()
    except Exception:
        pass
    return Path(os.getcwd()).resolve().as_posix()

CLEARANGLE_JSON = os.path.join(CAS_SCRIPTS_ROOT, 'cam_order.json').replace('\\', '/')
CLEARANGLE_LIGHTS = r'//inferno2/projects/common/home/quw/cas_scripts/cas_lights.mb'.replace('\\', '/')
CLEARANGLE_CHARTS = r'//inferno2/projects/common/home/quw/cas_scripts/charts.mb'.replace('\\', '/')
DEFAULT_CAM_ORDER_JSON = CLEARANGLE_JSON

RAW_EXTS = {
    '.dng', '.cr2', '.cr3', '.nef', '.arw', '.raf', '.rw2', '.orf', '.srw',
    '.3fr', '.erf', '.kdc', '.mef', '.mrw', '.nrw', '.pef', '.r3d', '.sr2', '.x3f'
}
EXR_EXTS = {'.exr'}
MM_DIR = 'imageplanes_mm_orig'

# Subfolder names
DIR_CAMERA = 'camera'
DIR_IMAGEPLANES = 'imageplanes'
DIR_IMAGEPLANES_ORIG = 'imageplanes_orig'
DIR_STMAPS = 'stmaps'
DIR_RAW = 'raw'
DIR_GREY = 'grey'
DIR_CHART = 'chart'
DIR_CHROME = 'chrome'
DIR_MAYA = 'maya'
DIR_NUKE = 'nuke'
DIR_LIGHTS_EXPORT = 'lights_export'

# Export folders
DIR_EXPORT_LINEUP = 'lineup_export'
DIR_EXPORT_GREY = 'grey_export'
DIR_EXPORT_CHART = 'chart_export'
DIR_EXPORT_CHROME = 'chrome_export'
DIR_EXPORT_STMAPS = 'stmaps_export'
DIR_SCENE_EXPORT = 'scene_export'  # scene-level exports

# External Nuke template
NUKE_TEMPLATE_PATH = r'//inferno2/projects/common/home/quw/cas_scripts/template.nk'.replace('\\', '/')


# ----------------------------- Helpers -----------------------------
def _divider():
    d = QFrame()
    d.setStyleSheet('border: 1px solid rgb(60,60,60)')
    d.setFrameShadow(QFrame.Plain)
    d.setFrameShape(QFrame.HLine)
    d.setMinimumSize(300, 2)
    return d

def ensure_dir(path):
    if path and not os.path.exists(path):
        os.makedirs(path)

def list_scene_cameras(include_startup=False):
    cams = cmds.ls(type='camera') or []
    camTs = []
    for s in cams:
        t = cmds.listRelatives(s, parent=True, fullPath=True)
        if not t:
            continue
        t = t[0]
        try:
            if not include_startup and cmds.camera(t, q=True, startupCamera=True):
                continue
        except Exception:
            pass
        camTs.append(t)
    return sorted(set(camTs))

def get_camera_shape(camT):
    try:
        if not (camT and cmds.objExists(camT)):
            return None
        shapes = cmds.listRelatives(camT, shapes=True, fullPath=True) or []
        return shapes[0] if shapes else None
    except Exception:
        return None

def find_first_imageplane_on_camera_shape(camS):
    if not camS or not cmds.objExists(camS):
        return None
    ips = cmds.listConnections(camS, type='imagePlane') or []
    return ips[0] if ips else None

def list_scene_imageplanes():
    ips = cmds.ls(type='imagePlane') or []
    seen = []
    for ip in ips:
        if ip not in seen:
            seen.append(ip)
    return seen

def imageplane_file(ip):
    try:
        path = cmds.getAttr(ip + '.imageName') or ''
        return path.replace('\\', '/')
    except Exception:
        return ''

def list_imageplanes_on_camera_shape(camS):
    if not camS or not cmds.objExists(camS):
        return []
    ips = cmds.listConnections(camS, type='imagePlane') or []
    # preserve order but ensure unique
    seen = []
    for ip in ips:
        if ip not in seen:
            seen.append(ip)
    return seen

# Compatibility alias (handles older name variant)
def list_imageplane_on_camera_shape(camS):
    return list_imageplanes_on_camera_shape(camS)


def set_imageplane_display_only_if_current(ip):
    if not ip:
        return
    nodes = [ip]
    try:
        nodes += cmds.listRelatives(ip, shapes=True, fullPath=True) or []
    except Exception:
        pass
    for node in nodes:
        try:
            if cmds.objExists(node + '.displayOnlyIfCurrent'):
                cmds.setAttr(node + '.displayOnlyIfCurrent', 1)
        except Exception:
            continue


def enforce_scene_imageplanes_display_only_if_current():
    for ip in list_scene_imageplanes():
        set_imageplane_display_only_if_current(ip)

def _is_default_cam(cam):
    default_cams = set(cmds.listCameras(p=True) or [])
    return cam in default_cams or cam in ('persp', 'left', 'right', 'top', 'front')

def scene_path():
    try:
        p = cmds.file(q=True, sn=True) or ''
        return p.replace('\\', '/')
    except Exception:
        return ''

def maya_safe_name_from_stem(stem):
    if stem is None:
        return None
    name = stem.strip()
    name = name.replace('/', '*').replace('\\', '*').replace('|', '_')
    return name or None

def warn_on_existing_files(folder, parent_ui):
    try:
        if not os.path.isdir(folder):
            return 'keep'
        entries = [f for f in os.listdir(folder) if os.path.isfile(os.path.join(folder, f))]
        if not entries:
            return 'keep'
    except Exception:
        return 'keep'
    msg = (
        f'The folder:\n{folder}\ncontains {len(entries)} files.\n\n'
        'Choose an action:\nYes = Delete all files and recreate\n'
        'No = Keep files and append\nCancel = Abort'
    )
    buttons = QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel
    reply = QMessageBox.question(parent_ui, 'Existing files detected', msg, buttons, QMessageBox.Cancel)
    if reply == QMessageBox.Yes:
        for f in entries:
            try:
                os.remove(os.path.join(folder, f))
            except Exception as e:
                try:
                    parent_ui.log.append(f'Failed to remove {f}: {e}')
                except Exception:
                    pass
        return 'delete'
    elif reply == QMessageBox.No:
        return 'keep'
    else:
        return 'cancel'

def detect_sequence_components(path):
    if not path:
        return None
    d, fname = os.path.split(path)
    m = re.match(r"^(?P<base>.*?)(?P<frame>\d+)(?P<ext>\.[^.]+)$", fname)
    if m:
        return {'dir': d.replace('\\', '/'), 'base': m.group('base'), 'frame': int(m.group('frame')), 'ext': m.group('ext')}
    else:
        root, ext = os.path.splitext(fname)
        return {'dir': d.replace('\\', '/'), 'base': root, 'frame': None, 'ext': ext}

def get_or_create_lineup_camera():
    camT = (cmds.ls('LINEUP_CAM', type='transform') or [None])[0]
    if not camT:
        camT, _ = cmds.camera(n='LINEUP_CAM')
        camT = cmds.rename(camT, 'LINEUP_CAM')
    camS = get_camera_shape(camT)
    return camT, camS, (camS is not None)

def get_or_create_ip_on_camera(camT):
    camS = get_camera_shape(camT)
    if not camS:
        return None
    ip = find_first_imageplane_on_camera_shape(camS)
    if ip:
        set_imageplane_display_only_if_current(ip)
        return ip
    ip_nodes = cmds.imagePlane(camera=camT)
    ip = ip_nodes[0]
    set_imageplane_display_only_if_current(ip)
    return ip

def _match_stem_glob(stem, file_list):
    if not stem:
        return ''
    s = stem.lower()
    for p in file_list:
        base = os.path.basename(p).lower()
        if base.startswith(s):
            return p
    return ''

def remove_all_files_in_folder(folder):
    try:
        if not os.path.isdir(folder):
            return 0
        count = 0
        for f in os.listdir(folder):
            fp = os.path.join(folder, f)
            if os.path.isfile(fp):
                os.remove(fp)
                count += 1
        return count
    except Exception:
        return 0

def existing_sequence_frames(folder, base_name):
    # Return sorted list of frame numbers (and first extension) for base_name. Assumes filenames like base.####.ext.
    frames = []
    ext_found = None
    if not (folder and os.path.isdir(folder) and base_name):
        return frames, ext_found
    pattern = re.compile(rf'^{re.escape(base_name)}\.(\d+)(\.[^.]+)$')
    for f in os.listdir(folder):
        m = pattern.match(f)
        if m:
            try:
                frames.append(int(m.group(1)))
            except Exception:
                continue
            if ext_found is None:
                ext_found = m.group(2)
    frames.sort()
    return frames, ext_found

def files_identical(src, dst):
    try:
        return filecmp.cmp(src, dst, shallow=False)
    except Exception:
        return False

def show_overwrite_dialog(parent, title, message, include_wipe=False):
    dialog = QMessageBox(parent)
    dialog.setIcon(QMessageBox.Question)
    dialog.setWindowTitle(title)
    dialog.setText(message)
    btn_over = dialog.addButton('Overwrite', QMessageBox.AcceptRole)
    btn_skip = dialog.addButton('Skip', QMessageBox.RejectRole)
    btn_cancel = dialog.addButton('Cancel', QMessageBox.DestructiveRole)
    btn_wipe = None
    if include_wipe:
        btn_wipe = dialog.addButton('Wipe Folder', QMessageBox.ActionRole)
    dialog.exec_()
    clicked = dialog.clickedButton()
    if clicked == btn_over:
        return 'overwrite'
    if include_wipe and clicked == btn_wipe:
        return 'wipe'
    if clicked == btn_skip:
        return 'skip'
    return 'cancel'

def run_silent(cmd, **kwargs):
    """
    Run subprocess without popping up a console window (esp. on Windows).
    By default discard stdout/stderr to avoid pipe-buffer hangs & focus-stealing.
    """
    if os.name == 'nt':
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        kwargs.setdefault('startupinfo', startupinfo)
        kwargs.setdefault('creationflags', subprocess.CREATE_NO_WINDOW)
    if 'stdout' not in kwargs and 'stderr' not in kwargs:
        with open(os.devnull, 'w') as devnull:
            kwargs.setdefault('stdout', devnull)
            kwargs.setdefault('stderr', devnull)
            return subprocess.run(cmd, **kwargs)
    else:
        return subprocess.run(cmd, **kwargs)

# ----------------------------- cAPI helpers -----------------------------
def getListofProjects():
    try:
        shows = cAPI.Show.getShows('Active') or []
        items = []
        for s in shows:
            code = getattr(s, 'code', None) or getattr(s, 'name', None)
            if code:
                items.append(code)
        show_list = sorted(set(items))
        return list(show_list)
    except Exception:
        return []

def cAPI_assets_for_fixed_shot(show_code):
    try:
        show = cAPI.Show(show_code) if show_code else None
        shot = cAPI.Shot(show, 'SHR_shr_rsrc') if show else None
        if shot:
            mayaResources = shot.getResourcesByType('cache.maya.model') or []
            resNames = [x.name for x in mayaResources]
            return sorted(set([name.split('_')[-1] for name in resNames if name]))
    except Exception:
        pass
    return []

def build_pipeline_root(project_code, asset):
    return PIPELINE_ROOT_TEMPLATE.format(project=project_code or 'unknown', asset=asset or 'asset').replace('\\', '/')

# ----------------------------- Dialogs -----------------------------
class ImagePlaneListDialog(QDialog):
    def __init__(self, rows, title='ImagePlane Files', parent=None):
        super(ImagePlaneListDialog, self).__init__(parent)
        self.setWindowTitle(title)
        self.resize(900, 420)
        layout = QVBoxLayout(self)
        table = QTableWidget()
        table.setColumnCount(3)
        table.setHorizontalHeaderLabels(['Camera', 'ImagePlane Node', 'File'])
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        table.setRowCount(len(rows))
        for r, (cam, ip, f) in enumerate(rows):
            table.setItem(r, 0, QTableWidgetItem(cam))
            table.setItem(r, 1, QTableWidgetItem(ip or ''))
            table.setItem(r, 2, QTableWidgetItem(f or ''))
        layout.addWidget(table)
        row = QHBoxLayout()
        btn_copy = QPushButton('Copy to Clipboard')
        btn_close = QPushButton('Close')
        row.addWidget(btn_copy)
        row.addStretch(1)
        row.addWidget(btn_close)
        layout.addLayout(row)
        def copy_clip():
            parts = []
            for r in range(table.rowCount()):
                parts.append(f'{table.item(r, 0).text()}\t{table.item(r, 1).text()}\t{table.item(r, 2).text()}')
            QtWidgets.QApplication.clipboard().setText('\n'.join(parts))
            QMessageBox.information(self, 'Copied', 'List copied to clipboard.')
        btn_copy.clicked.connect(copy_clip)
        btn_close.clicked.connect(self.accept)

class ValidatePathsDialog(QDialog):
    def __init__(self, rows, parent=None):
        super(ValidatePathsDialog, self).__init__(parent)
        self.setWindowTitle('Validate ImagePlane Paths')
        self.resize(900, 420)
        lay = QVBoxLayout(self)
        total = len(rows)
        valid = sum(1 for r in rows if r['exists'])
        missing = total - valid
        summary = QLabel(f'Total: {total}   Valid: {valid}   Missing: {missing}')
        summary.setStyleSheet('font-weight: bold')
        lay.addWidget(summary)
        table = QTableWidget()
        table.setColumnCount(4)
        table.setHorizontalHeaderLabels(['Camera', 'ImagePlane Node', 'File', 'Exists'])
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        table.setRowCount(total)
        for r, row in enumerate(rows):
            cam_item = QTableWidgetItem(row['camera'])
            ip_item = QTableWidgetItem(row['ip'] or '')
            file_item = QTableWidgetItem(row['path'] or '')
            exists_item = QTableWidgetItem('Yes' if row['exists'] else 'No')
            color = QtGui.QColor(70, 150, 70) if row['exists'] else QtGui.QColor(180, 70, 70)
            exists_item.setForeground(QtGui.QBrush(color))
            table.setItem(r, 0, cam_item)
            table.setItem(r, 1, ip_item)
            table.setItem(r, 2, file_item)
            table.setItem(r, 3, exists_item)
        lay.addWidget(table)
        rowb = QHBoxLayout()
        btn_copy = QPushButton('Copy to Clipboard')
        btn_close = QPushButton('Close')
        rowb.addWidget(btn_copy)
        rowb.addStretch(1)
        rowb.addWidget(btn_close)
        lay.addLayout(rowb)
        def copy_tbl():
            parts = ['Camera\tImagePlane\tFile\tExists']
            for r in range(table.rowCount()):
                parts.append(f'{table.item(r, 0).text()}\t{table.item(r, 1).text()}\t{table.item(r, 2).text()}\t{table.item(r, 3).text()}')
            QtWidgets.QApplication.clipboard().setText('\n'.join(parts))
            QMessageBox.information(self, 'Copied', 'Validation table copied.')
        btn_copy.clicked.connect(copy_tbl)
        btn_close.clicked.connect(self.accept)

# ----------------------------- Main UI -----------------------------
class LineupCamTool(QMainWindow):
    def __init__(self, parent=None):
        super(LineupCamTool, self).__init__(parent)
        self.setWindowTitle('Lineup Camera Builder + Exports + RAW Processing')

        self._build_ui()
        self._init_pipeline_defaults()
        self._load_settings()
        self.refresh_camera_list()

        # Always-on-top
        self.setWindowFlag(QtCore.Qt.WindowStaysOnTopHint, True)
        self.setGeometry(650, 120, 760, 900)

    def _with_temp_no_ontop(self, func, *args, **kwargs):
        """Previously toggled always-on-top; now just call func directly."""
        return func(*args, **kwargs)

    def _build_ui(self):
        container = QWidget()
        main = QVBoxLayout(container)
        container.setStyleSheet("""
            QLabel { color: #e0e0e0; }
            QListWidget { background: #1b1b1b; color: #eaeaea; }
            QLineEdit, QTextEdit, QSpinBox, QDoubleSpinBox, QComboBox { background: #202022; color: #eaeaea; border: 1px solid #3a3a3a; }
            QGroupBox { color: #d0d0d0; border: 1px solid #3a3a3a; margin-top: 10px; }
            QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 3px; }
            QPushButton { background: #2d2f34; color: #f0f0f0; border: 1px solid #4a4a4a; padding: 6px 10px; }
            QPushButton:hover { background: #3a3d44; }
            QTableWidget { background: #1b1b1b; color: #eaeaea; gridline-color: #333; }
        """)

        # Pipeline selection (cAPI)
        g_pipe = QGroupBox('Pipeline Target')
        lay_pipe = QGridLayout()
        g_pipe.setLayout(lay_pipe)

        self.combo_project = QComboBox()
        self.line_username = QLineEdit(); self.line_username.setReadOnly(True)
        self.line_show = QLineEdit(); self.line_show.setReadOnly(True)
        self.line_shot_fixed = QLineEdit('SHR_shr_rsrc'); self.line_shot_fixed.setReadOnly(True)
        self.combo_asset = QComboBox(); self.combo_asset.setEditable(True)

        self.line_computed_root = QLineEdit(); self.line_computed_root.setReadOnly(True)

        row = 0
        lay_pipe.addWidget(QLabel('User:'), row, 0); lay_pipe.addWidget(self.line_username, row, 1)
        lay_pipe.addWidget(QLabel('Project:'), row, 2); lay_pipe.addWidget(self.combo_project, row, 3)
        row += 1
        lay_pipe.addWidget(QLabel('Show (selected):'), row, 0); lay_pipe.addWidget(self.line_show, row, 1)
        lay_pipe.addWidget(QLabel('Shot (fixed):'), row, 2); lay_pipe.addWidget(self.line_shot_fixed, row, 3)
        row += 1
        lay_pipe.addWidget(QLabel('Asset:'), row, 0); lay_pipe.addWidget(self.combo_asset, row, 1, 1, 3)
        row += 1
        lay_pipe.addWidget(QLabel('Computed Root:'), row, 0); lay_pipe.addWidget(self.line_computed_root, row, 1, 1, 3)
        main.addWidget(g_pipe)

        main.addWidget(_divider())

        # Tabs: Lineup + RAW
        self.tabs = QtWidgets.QTabWidget()
        self.tab_lineup = QWidget()
        self.tab_raw = QWidget()
        self.tabs.addTab(self.tab_lineup, "Lineup")
        self.tabs.addTab(self.tab_raw, "RAW Processing")
        main.addWidget(self.tabs)

        lineup = QVBoxLayout(self.tab_lineup)
        raw_layout = QVBoxLayout(self.tab_raw)

        # Cameras list and tools
        lineup.addWidget(QLabel('Select cameras (order matters). Drag to reorder.'))
        self.listCams = QListWidget()
        self.listCams.setSelectionMode(self.listCams.ExtendedSelection)
        self.listCams.setDragDropMode(QListWidget.InternalMove)
        lineup.addWidget(self.listCams)

        row_btns = QHBoxLayout()
        self.btn_refresh = QPushButton('Refresh Scene Cameras')
        self.btn_add_selected = QPushButton('Add Selected Cameras')
        self.btn_remove = QPushButton('Remove Selected')
        self.btn_clear_all = QPushButton('Clear All')
        row_btns.addWidget(self.btn_refresh)
        row_btns.addWidget(self.btn_add_selected)
        row_btns.addWidget(self.btn_remove)
        row_btns.addWidget(self.btn_clear_all)
        lineup.addLayout(row_btns)

        row_tools = QHBoxLayout()
        self.btn_rename_from_ip = QPushButton('Rename Cams From ImagePlane (Tx + Shape)')
        self.chk_prefix_underscore = QCheckBox('Prefix underscore to names'); self.chk_prefix_underscore.setChecked(True)
        self.btn_list_ip_files = QPushButton('List ImagePlane Files')
        self.btn_validate_paths = QPushButton('Validate ImagePlane Paths')
        self.btn_open_file_path_editor = QPushButton('Open File Path Editor')
        row_tools.addWidget(self.btn_rename_from_ip)
        row_tools.addWidget(self.chk_prefix_underscore)
        row_tools.addWidget(self.btn_list_ip_files)
        row_tools.addWidget(self.btn_validate_paths)
        row_tools.addWidget(self.btn_open_file_path_editor)
        lineup.addLayout(row_tools)

        # ClearAngle presets
        g_ca = QGroupBox('ClearAngle Presets')
        lay_ca = QHBoxLayout(g_ca)
        self.chk_clearangle_mode = QCheckBox('Use ClearAngle mode (preset cameras/lights)')
        self.combo_ca_preset = QComboBox(); self.combo_ca_preset.addItems(['LookdevA', 'Global'])
        self.chk_import_charts = QCheckBox('Import charts/spheres'); self.chk_import_charts.setChecked(True)
        self.chk_animate_lights = QCheckBox('Animate lights from preset'); self.chk_animate_lights.setChecked(False)
        lay_ca.addWidget(self.chk_clearangle_mode)
        lay_ca.addWidget(QLabel('Preset:'))
        lay_ca.addWidget(self.combo_ca_preset)
        lay_ca.addWidget(self.chk_import_charts)
        lay_ca.addWidget(self.chk_animate_lights)
        lay_ca.addStretch(1)
        lineup.addWidget(g_ca)
        lineup.addWidget(_divider())

        # Base name + manifest filename + start frame
        self.line_basename = QLineEdit('imageplane')

        row_start = QHBoxLayout()
        row_start.addWidget(QLabel('Start frame (build):'))
        self.spin_start = QSpinBox(); self.spin_start.setRange(-100000, 1000000); self.spin_start.setValue(DEFAULT_START_FRAME)
        row_start.addWidget(self.spin_start)
        self.btn_reset_ui = QPushButton('Reset UI to Defaults')
        row_start.addWidget(self.btn_reset_ui)
        lineup.addLayout(row_start)
        # RAW processing shares the same start frame control
        self.spin_und_start = self.spin_start
        # RAW and lineup share the same start frame control
        self.spin_und_start = self.spin_start

        # Advanced settings panel (hidden by default)
        self.adv_box = QGroupBox('Advanced Settings')
        self.adv_box.setVisible(True)
        adv_layout = QVBoxLayout()
        self.adv_box.setLayout(adv_layout)

        row_custom_root = QHBoxLayout()
        self.chk_custom_root = QCheckBox('Use Custom Root')
        self.line_custom_root = QLineEdit(); self.line_custom_root.setEnabled(False)
        self.btn_browse_custom_root = QPushButton('Browse...'); self.btn_browse_custom_root.setEnabled(False)
        row_custom_root.addWidget(self.chk_custom_root)
        row_custom_root.addWidget(self.line_custom_root)
        row_custom_root.addWidget(self.btn_browse_custom_root)
        row_custom_root.addStretch(1)
        adv_layout.addLayout(row_custom_root)

        row_manifest = QHBoxLayout()
        self.chk_custom_manifest = QCheckBox('Use custom manifest JSON')
        self.line_custom_manifest = QLineEdit()
        self.line_custom_manifest.setEnabled(False)
        self.btn_browse_custom_manifest = QPushButton('Browse...'); self.btn_browse_custom_manifest.setEnabled(False)
        self.btn_load_ui_from_manifest = QPushButton('Load UI from Manifest')
        row_manifest.addWidget(self.chk_custom_manifest)
        row_manifest.addWidget(self.line_custom_manifest)
        row_manifest.addWidget(self.btn_browse_custom_manifest)
        row_manifest.addWidget(self.btn_load_ui_from_manifest)
        adv_layout.addLayout(row_manifest)

        row_overwrite = QHBoxLayout()
        self.chk_overwrite_imageplanes = QCheckBox('Auto-overwrite imageplane folders')
        self.chk_overwrite_imageplanes.setChecked(True)
        row_overwrite.addWidget(self.chk_overwrite_imageplanes)
        row_overwrite.addStretch(1)
        adv_layout.addLayout(row_overwrite)

        row_copy_all = QHBoxLayout()
        self.chk_copy_all_imageplanes = QCheckBox('Copy all scene imagePlanes to imageplanes_orig (except LINEUP_CAM/ALT)')
        self.chk_copy_all_imageplanes.setChecked(True)
        row_copy_all.addWidget(self.chk_copy_all_imageplanes)
        row_copy_all.addStretch(1)
        adv_layout.addLayout(row_copy_all)

        row_matchmove = QHBoxLayout()
        self.chk_matchmove_cam = QCheckBox('Build MATCHMOVE_CAM from all scene cameras (excl. defaults/LINEUP)')
        self.chk_matchmove_cam.setChecked(False)
        row_matchmove.addWidget(self.chk_matchmove_cam)
        row_matchmove.addStretch(1)
        adv_layout.addLayout(row_matchmove)

        row_alt = QHBoxLayout()
        self.chk_create_alt_cam = QCheckBox('Create LINEUP_CAM_ALT with custom aspect')
        self.spin_alt_aspect = QDoubleSpinBox()
        self.spin_alt_aspect.setRange(0.1, 10.0)
        self.spin_alt_aspect.setDecimals(3)
        self.spin_alt_aspect.setSingleStep(0.01)
        self.spin_alt_aspect.setValue(1.667)  # default aspect for ALT cam
        row_alt.addWidget(self.chk_create_alt_cam)
        row_alt.addWidget(QLabel('Aspect:'))
        row_alt.addWidget(self.spin_alt_aspect)
        row_alt.addStretch(1)
        adv_layout.addLayout(row_alt)

        # Export toggles
        self.chk_export_fbx = QtWidgets.QCheckBox('Camera FBX')
        self.chk_export_usd = QtWidgets.QCheckBox('Camera USD')
        self.chk_export_abc = QtWidgets.QCheckBox('Camera ABC'); self.chk_export_abc.setChecked(True)
        self.chk_export_scene_fbx = QtWidgets.QCheckBox('Scene FBX')
        self.chk_export_scene_abc = QtWidgets.QCheckBox('Scene ABC')

        row_exp = QHBoxLayout()
        row_exp.addWidget(self.chk_export_fbx)
        row_exp.addWidget(self.chk_export_usd)
        row_exp.addWidget(self.chk_export_abc)
        row_exp.addWidget(self.chk_export_scene_fbx)
        row_exp.addWidget(self.chk_export_scene_abc)
        adv_layout.addLayout(row_exp)

        lineup.addWidget(self.adv_box)
        lineup.addWidget(_divider())

        # Build / Export buttons
        self.btn_build = QPushButton('Create Lineup Camera')
        self.btn_exports_only = QPushButton('Export Camera / Scene Data')

        primary_btn_style = """
            QPushButton {
                background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #1f6feb, stop:1 #1158c7);
                color: white; border: 1px solid #0b4ea2; border-radius: 6px;
                padding: 10px 16px; font-weight: 700; font-size: 14px;
            }
            QPushButton:hover { background: #2a7cf0; }
            QPushButton:pressed { background: #0f58c9; }
        """
        neutral_btn_style = """
            QPushButton {
                background: #3a3d44;
                color: #f0f0f0; border: 1px solid #5a5a5a; border-radius: 6px;
                padding: 10px 16px; font-weight: 700; font-size: 14px;
            }
            QPushButton:hover { background: #4a4d55; }
            QPushButton:pressed { background: #2e3036; }
        """

        self.btn_build.setStyleSheet(primary_btn_style)
        self.btn_exports_only.setStyleSheet(neutral_btn_style)
        self.btn_build.setMinimumHeight(38)
        self.btn_exports_only.setMinimumHeight(38)

        row_build = QHBoxLayout()
        row_build.addWidget(self.btn_build, 3)
        row_build.addWidget(self.btn_exports_only, 2)
        lineup.addLayout(row_build)

        lineup.addWidget(_divider())

        # ---------------------- RAW Processing Section ----------------------
        und_g = QGroupBox('RAW Image Processing (RAW + ST Maps)')
        und_l = QVBoxLayout(und_g)

        row_oiio = QHBoxLayout()
        row_oiio.addWidget(QLabel('oiiotool executable:'))
        self.line_oiio = QLineEdit(DEFAULT_OIIOTOOL)
        self.btn_oiio_browse = QPushButton('Browse...')
        row_oiio.addWidget(self.line_oiio); row_oiio.addWidget(self.btn_oiio_browse)
        und_l.addLayout(row_oiio)

        row_src = QHBoxLayout()
        row_src.addWidget(QLabel('ST maps source folder:'))
        self.line_src_st = QLineEdit()
        self.btn_src_st = QPushButton('Browse...')
        row_src.addWidget(self.line_src_st); row_src.addWidget(self.btn_src_st)
        und_l.addLayout(row_src)

        row_src2 = QHBoxLayout()
        row_src2.addWidget(QLabel('Camera RAW source folder:'))
        self.line_src_raw = QLineEdit()
        self.btn_src_raw = QPushButton('Browse...')
        row_src2.addWidget(self.line_src_raw); row_src2.addWidget(self.btn_src_raw)
        und_l.addLayout(row_src2)

        row_grey = QHBoxLayout()
        row_grey.addWidget(QLabel('Grey RAW folder:'))
        self.line_src_grey = QLineEdit()
        self.btn_src_grey = QPushButton('Browse...')
        row_grey.addWidget(self.line_src_grey); row_grey.addWidget(self.btn_src_grey)
        und_l.addLayout(row_grey)

        row_chart = QHBoxLayout()
        row_chart.addWidget(QLabel('Chart RAW folder:'))
        self.line_src_chart = QLineEdit()
        self.btn_src_chart = QPushButton('Browse...')
        row_chart.addWidget(self.line_src_chart); row_chart.addWidget(self.btn_src_chart)
        und_l.addLayout(row_chart)

        row_chrome = QHBoxLayout()
        row_chrome.addWidget(QLabel('Chrome RAW folder:'))
        self.line_src_chrome = QLineEdit()
        self.btn_src_chrome = QPushButton('Browse...')
        row_chrome.addWidget(self.line_src_chrome); row_chrome.addWidget(self.btn_src_chrome)
        und_l.addLayout(row_chrome)

        stch_group = QGroupBox('ST Map Channels')
        stch_lay = QHBoxLayout(stch_group)
        stch_lay.addWidget(QLabel('Use channels for (s,t):'))
        self.combo_st_mode = QComboBox(); self.combo_st_mode.addItems(['RGB (first 2 channels)', 'UV (u,v by name)', 'Custom'])
        self.line_st_custom = QLineEdit(); self.line_st_custom.setPlaceholderText('Custom: "0,1" or "u,v" etc.')
        stch_lay.addWidget(self.combo_st_mode); stch_lay.addWidget(self.line_st_custom)
        und_l.addWidget(stch_group)

        self.btn_scan_matches = QPushButton('Scan Matches (by manifest)')
        und_l.addWidget(self.btn_scan_matches)
        self.table_matches = QTableWidget()
        self.table_matches.setColumnCount(6)
        self.table_matches.setHorizontalHeaderLabels(['Index', 'Frame', 'Stem', 'ST Map', 'RAW', 'Status'])
        for i in range(6):
            mode = QHeaderView.ResizeToContents if i in (0, 1, 2, 5) else QHeaderView.Stretch
            self.table_matches.horizontalHeader().setSectionResizeMode(i, mode)
        und_l.addWidget(self.table_matches)

        row_uopt = QHBoxLayout()
        self.chk_und_debug = QCheckBox('oiiotool --debug')

        self.combo_highlight_mode = QComboBox()
        self.combo_highlight_mode.addItems(['Highlight Mode 0 (default)', 'Highlight Mode 2'])

        self.btn_und_process = QPushButton('Process RAW Images')
        accent_btn_style = """
            QPushButton {
                background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #ee6a20, stop:1 #c14f10);
                color: white; border: 1px solid #9a3f0d; border-radius: 6px;
                padding: 10px 16px; font-weight: 700; font-size: 14px;
            }
            QPushButton:hover { background: #f57c39; }
            QPushButton:pressed { background: #b7490f; }
        """
        self.btn_und_process.setStyleSheet(accent_btn_style)
        self.btn_und_process.setMinimumHeight(38)

        row_uopt.addWidget(self.chk_und_debug)
        row_uopt.addWidget(QLabel('RAW Highlight:'))
        row_uopt.addWidget(self.combo_highlight_mode)
        row_uopt.addStretch(1)
        row_uopt.addWidget(self.btn_und_process)
        und_l.addLayout(row_uopt)

        raw_layout.addWidget(und_g)
        raw_layout.addWidget(_divider())

        # Log
        self.btn_open_root = QPushButton('Open Root')
        main.addWidget(self.btn_open_root)
        main.addWidget(QLabel('Log:'))
        self.log = QTextEdit(); self.log.setReadOnly(True)
        self.log.setStyleSheet("color: #cfcfcf; background:#141414; font-family: Consolas, Monaco, monospace;")
        main.addWidget(self.log)

        self.setCentralWidget(container)

        # Signals
        self.btn_refresh.clicked.connect(self.refresh_camera_list)
        self.btn_add_selected.clicked.connect(self.add_selected_from_scene)
        self.btn_remove.clicked.connect(self.remove_selected)
        self.btn_clear_all.clicked.connect(self.clear_all_cameras)
        self.btn_build.clicked.connect(self.build_lineup)
        self.btn_exports_only.clicked.connect(self.export_only)
        self.btn_rename_from_ip.clicked.connect(self.rename_cameras_from_ip)
        self.btn_list_ip_files.clicked.connect(self.show_ip_list_dialog)
        self.btn_validate_paths.clicked.connect(self.validate_paths_dialog)
        self.btn_open_file_path_editor.clicked.connect(lambda: self._with_temp_no_ontop(self.open_file_path_editor))
        self.btn_open_root.clicked.connect(lambda: self._with_temp_no_ontop(self.open_und_root))
        self.btn_reset_ui.clicked.connect(self.reset_ui_defaults)

        self.chk_clearangle_mode.toggled.connect(self._on_clearangle_toggled)
        self.combo_ca_preset.currentTextChanged.connect(lambda _: self._refresh_clearangle_camera_list())

        self.combo_project.currentTextChanged.connect(self._on_project_changed)
        self.combo_asset.currentTextChanged.connect(self._update_computed_root)
        self.chk_custom_root.toggled.connect(self._toggle_custom_root)
        self.chk_custom_manifest.toggled.connect(self._toggle_custom_manifest)
        self.btn_browse_custom_root.clicked.connect(lambda: self._with_temp_no_ontop(self._pick_custom_root))
        self.btn_browse_custom_manifest.clicked.connect(lambda: self._with_temp_no_ontop(self._pick_custom_manifest))

        self.btn_load_ui_from_manifest.clicked.connect(lambda: self._with_temp_no_ontop(self.load_ui_from_manifest))

        self.btn_src_st.clicked.connect(lambda: self._with_temp_no_ontop(self.pick_src_st))
        self.btn_src_raw.clicked.connect(lambda: self._with_temp_no_ontop(self.pick_src_raw))
        self.btn_src_grey.clicked.connect(lambda: self._with_temp_no_ontop(self.pick_src_grey))
        self.btn_src_chart.clicked.connect(lambda: self._with_temp_no_ontop(self.pick_src_chart))
        self.btn_src_chrome.clicked.connect(lambda: self._with_temp_no_ontop(self.pick_src_chrome))
        self.btn_oiio_browse.clicked.connect(lambda: self._with_temp_no_ontop(self.pick_oiiotool))
        self.btn_scan_matches.clicked.connect(self.scan_matches)
        self.btn_und_process.clicked.connect(self.undistort_process)

        # Ensure any legacy Nuke-only buttons shipped with older layouts stay hidden
        self._hide_nuke_only_buttons()

    # ---------------- Pipeline UI helpers ----------------
    def _init_pipeline_defaults(self):
        user_name = os.getenv('USERNAME') or getpass.getuser() or 'unknown'
        self.line_username.setText(user_name)

        projects = getListofProjects()
        self.combo_project.clear()
        self.combo_project.addItems(projects)

        env_show = os.getenv('SCL_SHOW_CODE') or ''
        # Env wins over saved prefs; fall back to first item if not found
        if env_show:
            idx = self.combo_project.findText(env_show)
            if idx >= 0:
                self.combo_project.setCurrentIndex(idx)
            else:
                self.combo_project.setCurrentIndex(0 if self.combo_project.count() else -1)
        self.line_show.setText(self.combo_project.currentText().strip())
        self._on_project_changed()

    def _on_project_changed(self):
        show_code = self.combo_project.currentText().strip()
        self.line_show.setText(show_code)
        assets = cAPI_assets_for_fixed_shot(show_code)
        cur_asset = self.combo_asset.currentText()
        self.combo_asset.blockSignals(True)
        self.combo_asset.clear()
        if assets:
            self.combo_asset.addItems(assets)
            idx = self.combo_asset.findText(cur_asset)
            if idx >= 0:
                self.combo_asset.setCurrentIndex(idx)
            else:
                self.combo_asset.setCurrentIndex(0)
        self.combo_asset.blockSignals(False)
        self._update_computed_root()

    def _update_computed_root(self):
        show_code = self.line_show.text().strip()
        asset = self.combo_asset.currentText().strip()
        root = build_pipeline_root(show_code, asset)
        self.line_computed_root.setText(root)

    def _toggle_custom_root(self, state):
        self.line_custom_root.setEnabled(state)
        self.btn_browse_custom_root.setEnabled(state)
        if not state:
            self.line_custom_root.setText('')
            self._update_computed_root()

    def _toggle_custom_manifest(self, state):
        self.line_custom_manifest.setEnabled(state)
        self.btn_browse_custom_manifest.setEnabled(state)
        if not state:
            self.line_custom_manifest.setText('')

    def _pick_custom_root(self):
        p = QFileDialog.getExistingDirectory(self, 'Choose custom root')
        if p:
            self.line_custom_root.setText(p.replace('\\', '/'))

    def _pick_custom_manifest(self):
        p, _ = QFileDialog.getOpenFileName(self, 'Choose manifest JSON', '', 'JSON (*.json)')
        if p:
            self.line_custom_manifest.setText(p.replace('\\', '/'))
            self.chk_custom_manifest.setChecked(True)

    def reset_ui_defaults(self):
        self.chk_custom_root.setChecked(False)
        self.line_custom_root.setText('')
        self.chk_custom_manifest.setChecked(False)
        self.line_custom_manifest.setText('')
        self.line_basename.setText('imageplane')
        self.spin_start.setValue(DEFAULT_START_FRAME)
        self.chk_matchmove_cam.setChecked(False)
        self.chk_clearangle_mode.setChecked(False)
        self.chk_create_alt_cam.setChecked(False)
        self.spin_alt_aspect.setValue(1.667)
        for line_edit in (
            self.line_src_st,
            self.line_src_raw,
            self.line_src_grey,
            self.line_src_chart,
            self.line_src_chrome,
        ):
            line_edit.setText('')
        self.combo_st_mode.setCurrentIndex(0)
        self.line_st_custom.setText('')
        self.combo_highlight_mode.setCurrentIndex(0)
        self.line_oiio.setText(DEFAULT_OIIOTOOL)
        self._update_computed_root()
        self.refresh_camera_list()
        self.log_msg('UI reset to defaults (start frame 1001, matchmove off, raw folders cleared).')

    def current_root(self):
        if self.chk_custom_root.isChecked() and self.line_custom_root.text().strip():
            return self.line_custom_root.text().strip()
        return self.line_computed_root.text().strip()

    # ------------- Settings persistence -------------
    def _load_settings(self):
        s = QtCore.QSettings('Scanline', 'LineupCamTool')

        size = s.value('window/size')
        pos = s.value('window/pos')
        if isinstance(size, QtCore.QSize):
            self.resize(size)
        if isinstance(pos, QtCore.QPoint):
            self.move(pos)

        proj = s.value('pipeline/project', '', type=str)
        if proj:
            idx = self.combo_project.findText(proj)
            if idx >= 0:
                self.combo_project.setCurrentIndex(idx)

        asset = s.value('pipeline/asset', '', type=str)
        if asset:
            idx = self.combo_asset.findText(asset)
            if idx >= 0:
                self.combo_asset.setCurrentIndex(idx)

        custom_root_checked = s.value('pipeline/customRootChecked', False, type=bool)
        self.chk_custom_root.setChecked(custom_root_checked)
        custom_root_path = s.value('pipeline/customRootPath', '', type=str)
        self.line_custom_root.setText(custom_root_path)

        self.line_basename.setText(s.value('lineup/baseName', 'imageplane', type=str))
        self.spin_start.setValue(s.value('lineup/startFrame', DEFAULT_START_FRAME, type=int))
        self.chk_overwrite_imageplanes.setChecked(s.value('lineup/overwriteImageplanes', True, type=bool))
        self.chk_copy_all_imageplanes.setChecked(s.value('lineup/copyAllImageplanes', True, type=bool))
        self.chk_import_charts.setChecked(s.value('lineup/importCharts', True, type=bool))
        self.chk_animate_lights.setChecked(s.value('lineup/animateLights', False, type=bool))
        self.chk_matchmove_cam.setChecked(s.value('lineup/matchmoveCam', False, type=bool))
        # Always start with ClearAngle mode OFF (do not persist last state)
        self.chk_clearangle_mode.setChecked(False)
        ca_preset = s.value('lineup/clearanglePreset', 'LookdevA', type=str)
        idx_ca = self.combo_ca_preset.findText(ca_preset)
        if idx_ca >= 0:
            self.combo_ca_preset.setCurrentIndex(idx_ca)
        self.chk_create_alt_cam.setChecked(s.value('lineup/createAlt', False, type=bool))
        self.spin_alt_aspect.setValue(float(s.value('lineup/altAspect', 1.667, type=float)))
        self.chk_custom_manifest.setChecked(s.value('raw/customManifestEnabled', False, type=bool))
        self.line_custom_manifest.setText(s.value('raw/customManifestPath', '', type=str))
        self.line_oiio.setText(s.value('raw/oiiotool', DEFAULT_OIIOTOOL, type=str))
        self.line_src_st.setText(s.value('raw/srcSt', '', type=str))
        self.line_src_raw.setText(s.value('raw/srcRaw', '', type=str))
        self.line_src_grey.setText(s.value('raw/srcGrey', '', type=str))
        self.line_src_chart.setText(s.value('raw/srcChart', '', type=str))
        self.line_src_chrome.setText(s.value('raw/srcChrome', '', type=str))
        self.combo_st_mode.setCurrentIndex(s.value('raw/stModeIndex', 0, type=int))
        self.line_st_custom.setText(s.value('raw/stCustom', '', type=str))
        self.chk_und_debug.setChecked(s.value('raw/debug', False, type=bool))
        self.combo_highlight_mode.setCurrentIndex(s.value('raw/highlightModeIndex', 0, type=int))

    def _save_settings(self):
        s = QtCore.QSettings('Scanline', 'LineupCamTool')
        s.setValue('window/size', self.size())
        s.setValue('window/pos', self.pos())
        s.setValue('pipeline/project', self.combo_project.currentText())
        s.setValue('pipeline/asset', self.combo_asset.currentText())
        s.setValue('pipeline/customRootChecked', self.chk_custom_root.isChecked())
        s.setValue('pipeline/customRootPath', self.line_custom_root.text())
        s.setValue('lineup/baseName', self.line_basename.text())
        s.setValue('lineup/startFrame', int(self.spin_start.value()))
        s.setValue('lineup/overwriteImageplanes', self.chk_overwrite_imageplanes.isChecked())
        s.setValue('lineup/copyAllImageplanes', self.chk_copy_all_imageplanes.isChecked())
        s.setValue('lineup/importCharts', self.chk_import_charts.isChecked())
        s.setValue('lineup/animateLights', self.chk_animate_lights.isChecked())
        s.setValue('lineup/matchmoveCam', self.chk_matchmove_cam.isChecked())
        s.setValue('lineup/clearangleMode', self.chk_clearangle_mode.isChecked())
        s.setValue('lineup/clearanglePreset', self.combo_ca_preset.currentText())
        s.setValue('lineup/createAlt', self.chk_create_alt_cam.isChecked())
        s.setValue('lineup/altAspect', float(self.spin_alt_aspect.value()))
        s.setValue('raw/customManifestEnabled', self.chk_custom_manifest.isChecked())
        s.setValue('raw/customManifestPath', self.line_custom_manifest.text())
        s.setValue('raw/oiiotool', self.line_oiio.text())
        s.setValue('raw/srcSt', self.line_src_st.text())
        s.setValue('raw/srcRaw', self.line_src_raw.text())
        s.setValue('raw/srcGrey', self.line_src_grey.text())
        s.setValue('raw/srcChart', self.line_src_chart.text())
        s.setValue('raw/srcChrome', self.line_src_chrome.text())
        s.setValue('raw/stModeIndex', int(self.combo_st_mode.currentIndex()))
        s.setValue('raw/stCustom', self.line_st_custom.text())
        s.setValue('raw/debug', self.chk_und_debug.isChecked())
        s.setValue('raw/highlightModeIndex', int(self.combo_highlight_mode.currentIndex()))

    def closeEvent(self, event):
        try:
            self._save_settings()
        except Exception as e:
            print('Failed to save LineupCamTool settings:', e)
        try:
            super(LineupCamTool, self).closeEvent(event)
        except Exception:
            QMainWindow.closeEvent(self, event)

    # ------------- UI helpers and core camera list -------------
    def log_msg(self, m):
        self.log.append(m)
        print(m)

    def refresh_camera_list(self):
        self.listCams.clear()
        for cam in list_scene_cameras(include_startup=False):
            self.listCams.addItem(QListWidgetItem(cam))

    def add_selected_from_scene(self):
        sel = cmds.ls(sl=True, type='transform') or []
        cams = []
        for t in sel:
            shapes = cmds.listRelatives(t, shapes=True, fullPath=True) or []
            if shapes and cmds.nodeType(shapes[0]) == 'camera':
                cams.append(t)
        for cam in cams:
            self.listCams.addItem(QListWidgetItem(cam))

    def remove_selected(self):
        for item in self.listCams.selectedItems():
            self.listCams.takeItem(self.listCams.row(item))

    def clear_all_cameras(self):
        self.listCams.clear()

    def _hide_nuke_only_buttons(self):
        """Hide any leftover "Generate Nuke Script Only" buttons from legacy layouts."""
        try:
            for btn in self.findChildren(QtWidgets.QPushButton):
                text = (btn.text() or '').lower()
                if 'nuke' in text and 'only' in text:
                    btn.hide()
                    btn.setEnabled(False)
        except Exception as e:
            self.log_msg(f'Failed to hide legacy Nuke-only button(s): {e}')

    # ------------- Renamer -------------
    def rename_cameras_from_ip(self):
        cams = [self.listCams.item(i).text() for i in range(self.listCams.count())]
        if not cams:
            QMessageBox.warning(self, 'No cameras', 'Add cameras to the list first.')
            return
        add_prefix = self.chk_prefix_underscore.isChecked()
        existing_transforms = set(cmds.ls(transforms=True) or [])
        existing_dagnodes = set(cmds.ls() or [])
        rename_map = {}
        for camT in cams:
            camS = get_camera_shape(camT)
            if not camS or cmds.nodeType(camS) != 'camera':
                self.log_msg(f'Skip: {camT} has no valid camera shape.')
                continue
            ip = find_first_imageplane_on_camera_shape(camS)
            if not ip:
                self.log_msg(f'Skip: {camT} has no imagePlane connected.')
                continue
            img = imageplane_file(ip)
            if not img:
                self.log_msg(f'Skip: {camT} imagePlane has empty imageName.')
                continue
            stem = os.path.splitext(os.path.basename(img))[0]
            safe_base = maya_safe_name_from_stem(stem)
            if not safe_base:
                self.log_msg(f'Skip: Derived empty name for {camT}')
                continue
            name_base = f'_{safe_base}' if add_prefix else safe_base
            desired_tx = name_base
            desired_shape = f'{name_base}_camShape'
            new_tx = desired_tx
            i = 1
            while new_tx in existing_transforms:
                i += 1
                new_tx = f'{desired_tx}_{i}'
            new_shape = desired_shape
            j = 1
            while new_shape in existing_dagnodes:
                j += 1
                new_shape = f'{desired_shape}_{j}'
            try:
                final_tx = cmds.rename(camT, new_tx)
                existing_transforms.add(final_tx)
                rename_map[camT] = final_tx
                self.log_msg(f'Renamed transform: {camT} -> {final_tx}')
            except Exception as e:
                self.log_msg(f'Failed to rename {camT}: {e}')
                continue
            try:
                camS_after = get_camera_shape(final_tx)
                if camS_after and cmds.objExists(camS_after):
                    sname = new_shape
                    k = 1
                    while sname in existing_dagnodes:
                        k += 1
                        sname = f'{desired_shape}_{k}'
                    final_shape = cmds.rename(camS_after, sname)
                    existing_dagnodes.add(final_shape)
                    self.log_msg(f'Renamed shape: {camS_after} -> {final_shape}')
            except Exception as e:
                self.log_msg(f'Failed to rename shape for {final_tx}: {e}')
        if rename_map:
            for idx in range(self.listCams.count()):
                t = self.listCams.item(idx).text()
                if t in rename_map:
                    self.listCams.item(idx).setText(rename_map[t])

    # ------------- Info/Validation -------------
    def show_ip_list_dialog(self):
        cams = [self.listCams.item(i).text() for i in range(self.listCams.count())]
        if not cams:
            QMessageBox.information(self, 'No cameras', 'Add cameras to the list first.')
            return
        rows = []
        for cam in cams:
            camS = get_camera_shape(cam)
            ip = find_first_imageplane_on_camera_shape(camS) if camS else None
            f = imageplane_file(ip) if ip else ''
            rows.append((cam, ip or '', f or ''))
        dlg = ImagePlaneListDialog(rows, 'ImagePlane Files', self)
        self._with_temp_no_ontop(dlg.exec_)

    def validate_paths_dialog(self):
        cams = [self.listCams.item(i).text() for i in range(self.listCams.count())]
        if not cams:
            QMessageBox.information(self, 'No cameras', 'Add cameras to the list first.')
            return
        rows = []
        for cam in cams:
            camS = get_camera_shape(cam)
            ip = find_first_imageplane_on_camera_shape(camS) if camS else None
            f = imageplane_file(ip) if ip else ''
            exists = os.path.exists(f) if f else False
            rows.append({'camera': cam, 'ip': ip or '', 'path': f or '', 'exists': exists})
        dlg = ValidatePathsDialog(rows, self)
        self._with_temp_no_ontop(dlg.exec_)

    def open_file_path_editor(self):
        try:
            mel.eval('FilePathEditor;')
        except Exception:
            try:
                mel.eval('filePathEditor;')
            except Exception as e2:
                self.log_msg(f'Failed to open File Path Editor: {e2}')

    # ------------- ClearAngle presets -------------
    def _load_clearangle_config(self, preset_name):
        try:
            with open(CLEARANGLE_JSON, 'r') as f:
                data = json.load(f)
            cfgs = data.get('configs') or {}
            if preset_name in cfgs:
                return cfgs[preset_name]
        except Exception as e:
            self.log_msg(f'ClearAngle config load failed: {e}')
        return None

    def _refresh_clearangle_camera_list(self):
        if not self.chk_clearangle_mode.isChecked():
            return
        cfg = self._load_clearangle_config(self.combo_ca_preset.currentText())
        targets = (cfg or {}).get('targets') or []
        if not targets:
            self.log_msg('ClearAngle: no targets in config.')
            return
        cams = list_scene_cameras(include_startup=False)
        resolved = []
        for token in targets:
            match = [c for c in cams if token in c]
            if match:
                resolved.append(match[0])
            else:
                self.log_msg(f'ClearAngle: token "{token}" not found in scene.')
        self.listCams.clear()
        for c in resolved:
            self.listCams.addItem(QListWidgetItem(c))

    def _on_clearangle_toggled(self, state):
        enabled = not state
        for w in [self.listCams, self.btn_add_selected, self.btn_remove, self.btn_clear_all, self.btn_refresh, self.btn_rename_from_ip, self.btn_list_ip_files, self.btn_validate_paths]:
            try:
                w.setEnabled(enabled)
            except Exception:
                pass
        # Visual indicator on camera list when ClearAngle is active
        if not hasattr(self, '_orig_list_style'):
            self._orig_list_style = self.listCams.styleSheet()
        if state:
            self.listCams.setStyleSheet(self._orig_list_style + " QListWidget { background: #2b3342; color: #f0f0f0; }")
            # Default ClearAngle start frame suggestion
            self.spin_start.setValue(1201)
        else:
            self.listCams.setStyleSheet(self._orig_list_style)
        if state:
            self._refresh_clearangle_camera_list()

    def _import_clearangle_charts(self):
        if not self.chk_import_charts.isChecked():
            return
        if cmds.objExists('color_charts') or cmds.objExists('CHARTS'):
            return
        try:
            cmds.file(CLEARANGLE_CHARTS, i=True)
            self.log_msg('Imported ClearAngle charts.')
        except Exception as e:
            self.log_msg(f'Failed to import charts: {e}')

    def _import_clearangle_lights(self):
        if cmds.objExists('CAS_LIGHTS'):
            return
        try:
            cmds.file(CLEARANGLE_LIGHTS, i=True)
            self.log_msg('Imported ClearAngle lights.')
        except Exception as e:
            self.log_msg(f'Failed to import ClearAngle lights: {e}')

    def _apply_clearangle_lighting_mode(self):
        preset = self.combo_ca_preset.currentText()
        cfg = self._load_clearangle_config(preset) or {}
        mode = (cfg.get('mode') or '').lower()
        lights_off = [s.lower() for s in cfg.get('lights_off', [])]
        lights_map = cfg.get('lights', {}) or {}
        targets = cfg.get('targets', []) or []
        all_lights = cmds.ls('*bank?_*', type='transform') or []
        start_frame = int(self.spin_start.value())
        if not all_lights:
            self.log_msg('ClearAngle lights: no lights found to apply preset.')
            return

        # Always clear existing visibility keys before applying preset
        for L in all_lights:
            try:
                cmds.cutKey(L, at='visibility', clear=True)
            except Exception:
                pass

        if mode == 'global' and self.chk_animate_lights.isChecked():
            for L in all_lights:
                name_l = L.lower()
                state = 0 if any(off in name_l for off in lights_off) else 1
                try:
                    cmds.setAttr(L + '.visibility', state)
                    cmds.setKeyframe(L, at='visibility', t=start_frame, v=state)
                    cmds.setKeyframe(L, at='visibility', t=start_frame + max(0, len(targets) - 1), v=state)
                except Exception:
                    pass
            self.log_msg(f'ClearAngle lights: applied GLOBAL preset (off={lights_off}) from frame {start_frame}.')
            return

        # Animated (LookdevA) – rebuild visibility keys from config + camera order
        if not self.chk_animate_lights.isChecked():
            self.log_msg('ClearAngle lights: animation skipped (Animate lights is OFF).')
            return
        # First: all lights on at start
        for L in all_lights:
            try:
                cmds.setAttr(L + '.visibility', 1)
                cmds.setKeyframe(L, at='visibility', t=start_frame, v=1)
            except Exception:
                pass

        for idx, cam_token in enumerate(targets):
            frame = start_frame + idx
            # all off at frame
            for L in all_lights:
                try:
                    cmds.setAttr(L + '.visibility', 0)
                    cmds.setKeyframe(L, at='visibility', t=frame, v=0)
                except Exception:
                    pass
            # turn on mapped lights
            for lname in lights_map.get(cam_token, []):
                matches = [x for x in all_lights if lname in x]
                if not matches:
                    self.log_msg(f'ClearAngle LookdevA: light token "{lname}" not found for {cam_token}')
                    continue
                try:
                    cmds.setAttr(matches[0] + '.visibility', 1)
                    cmds.setKeyframe(matches[0], at='visibility', t=frame, v=1)
                except Exception:
                    pass

        self.log_msg(f'ClearAngle lights: applied {preset} preset across {len(targets)} frames starting {start_frame}.')

    def _prompt_imageplane_overwrite(self, img_dir, img_orig_dir, base_name):
        def _count_files(path):
            try:
                return len([f for f in os.listdir(path) if os.path.isfile(os.path.join(path, f))])
            except Exception:
                return 0

        counts = {
            'Imageplanes': _count_files(img_dir),
            'Imageplanes (orig)': _count_files(img_orig_dir)
        }
        total = sum(counts.values())
        if total == 0:
            return 'overwrite'

        lines = [f'{k}: {v}' for k, v in counts.items()]
        msg = (
            f'Existing lineup files detected for base "{base_name}".\n\n' +
            '\n'.join(lines) +
            '\n\nChoose action:\n'
            'Overwrite = keep files, replace matching names\n'
            'Wipe Folder = delete ALL files in these folders first\n'
            'Append = keep existing files, skip duplicates and continue numbering\n'
            'Cancel = abort build'
        )
        dlg = QMessageBox(self)
        dlg.setWindowTitle('Existing Imageplanes')
        dlg.setIcon(QMessageBox.Question)
        dlg.setText(msg)
        btn_over = dlg.addButton('Overwrite', QMessageBox.YesRole)
        btn_wipe = dlg.addButton('Wipe Folder', QMessageBox.ActionRole)
        btn_append = dlg.addButton('Append', QMessageBox.NoRole)
        btn_cancel = dlg.addButton('Cancel', QMessageBox.RejectRole)
        self._with_temp_no_ontop(dlg.exec_)
        clicked = dlg.clickedButton()
        if clicked == btn_wipe:
            return 'wipe'
        if clicked == btn_append:
            return 'append'
        if clicked == btn_over:
            return 'overwrite'
        return 'cancel'

    def _copy_ip_to_orig(self, ip, src_path, img_orig_dir, append_mode=False, overwrite_mode=True):
        """Copy imagePlane file into imageplanes_orig unless identical and append_mode."""
        if not (ip and src_path and os.path.exists(src_path)):
            return None
        ensure_dir(img_orig_dir)
        dst_path = os.path.join(img_orig_dir, os.path.basename(src_path)).replace('\\', '/')

        if os.path.exists(dst_path):
            if files_identical(src_path, dst_path):
                self.log_msg(f'Keep existing original (identical): {dst_path}')
            elif append_mode and not overwrite_mode:
                self.log_msg(f'Append mode: skip overwrite of different file {dst_path}')
                return dst_path
            else:
                try:
                    shutil.copy2(src_path, dst_path)
                    self.log_msg(f'Overwrite original: {dst_path}')
                except Exception as e:
                    self.log_msg(f'Failed to overwrite {dst_path}: {e}')
        else:
            try:
                shutil.copy2(src_path, dst_path)
                self.log_msg(f'Copied original: {dst_path}')
            except Exception as e:
                self.log_msg(f'Failed to copy {src_path} -> {dst_path}: {e}')
                return None

        try:
            cmds.setAttr(ip + '.imageName', dst_path, type='string')
            set_imageplane_display_only_if_current(ip)
        except Exception as e:
            self.log_msg(f'Failed to rewire {ip} to {dst_path}: {e}')
        return dst_path

    # ------------- Export helpers -------------
    def _ensure_root_subdirs(self, root):
        subdirs = [
            DIR_CAMERA, DIR_IMAGEPLANES, DIR_IMAGEPLANES_ORIG, DIR_STMAPS,
            DIR_RAW, DIR_GREY, DIR_CHART, DIR_CHROME, DIR_MAYA, DIR_NUKE,
            DIR_EXPORT_LINEUP, DIR_EXPORT_GREY, DIR_EXPORT_CHART,
            DIR_EXPORT_CHROME, DIR_EXPORT_STMAPS, DIR_SCENE_EXPORT,
            DIR_LIGHTS_EXPORT
        ]
        for s in subdirs:
            ensure_dir(os.path.join(root, s).replace('\\', '/'))

    def _manifest_path(self, root, base_name):
        if not base_name:
            base_name = 'imageplane'
        name = f'{base_name}_lineup_manifest.json'
        return os.path.join(root, name).replace('\\', '/')

    def _active_manifest_path(self, root=None, base_name=None, allow_dialog=False):
        if self.chk_custom_manifest.isChecked() and self.line_custom_manifest.text().strip():
            return self.line_custom_manifest.text().strip().replace('\\', '/')
        root = root or self.current_root()
        base_name = base_name or (self.line_basename.text().strip() or 'imageplane')
        p = self._manifest_path(root, base_name)
        if allow_dialog and not os.path.exists(p):
            path, _ = QFileDialog.getOpenFileName(self, 'Choose manifest JSON', '', 'JSON (*.json)')
            if path:
                self.line_custom_manifest.setText(path.replace('\\', '/'))
                self.chk_custom_manifest.setChecked(True)
                return path.replace('\\', '/')
        return p

    def export_camera_fbx(self, camT, start_frame, end_frame, out_dir, name='LINEUP_CAM'):
        ensure_dir(out_dir)
        out_path = os.path.join(out_dir, f'{name}.fbx').replace('\\', '/')
        try:
            cmds.select(camT, r=True)
            mel.eval('FBXResetExport;')
            mel.eval('FBXExportInAscii -v false;')
            mel.eval('FBXExportBakeComplexAnimation -v true;')
            mel.eval(f'FBXExportBakeComplexStart -v {start_frame};')
            mel.eval(f'FBXExportBakeComplexEnd -v {end_frame};')
            mel.eval('FBXExportBakeComplexStep -v 1;')
            mel.eval('FBXExportCameras -v true;')
            mel.eval('FBXExportLights -v false;')
            mel.eval('FBXExportSkins -v false;')
            mel.eval('FBXExportShapes -v false;')
            mel.eval('FBXExportConstraints -v false;')
            mel.eval('FBXExportEmbeddedTextures -v false;')
            self._with_temp_no_ontop(lambda: mel.eval(f'FBXExport -f "{out_path}" -s;'))
            self.log_msg(f'Exported Camera FBX: {out_path}')
            return out_path
        except Exception as e:
            self.log_msg(f'FBX export failed: {e}')
            return None

    def export_camera_abc(self, camT, start_frame, end_frame, out_dir, name='LINEUP_CAM'):
        ensure_dir(out_dir)
        out_path = os.path.join(out_dir, f'{name}.abc').replace('\\', '/')
        try:
            cmd = f'-frameRange {start_frame} {end_frame} -step 1 -worldSpace -dataFormat ogawa -root {camT} -file "{out_path}"'
            mel_cmd = 'AbcExport -j "{}";'.format(cmd.replace('"', '\\"'))
            self._with_temp_no_ontop(lambda: mel.eval(mel_cmd))
            self.log_msg(f'Exported Camera Alembic: {out_path}')
            return out_path
        except Exception as e:
            self.log_msg(f'Alembic export failed: {e}')
            return None

    def export_camera_usd(self, camT, start_frame, end_frame, out_dir, name='LINEUP_CAM'):
        ensure_dir(out_dir)
        out_path = os.path.join(out_dir, f'{name}.usda').replace('\\', '/')
        try:
            cmds.select(camT, r=True)
            def do_export():
                try:
                    cmds.mayaUSDExport(
                        file=out_path, selection=True, exportAnimation=True,
                        frameRange=(start_frame, end_frame),
                        exportUVs=False, exportColorSets=False,
                        defaultMeshScheme='none', shadingMode='none'
                    )
                except Exception:
                    opt = f'-file "{out_path}" -selection -exportAnimation -frameRange {start_frame} {end_frame} -shadingMode none'
                    mel.eval('mayaUSDExport ' + opt + ';')
            self._with_temp_no_ontop(do_export)
            self.log_msg(f'Exported Camera USD: {out_path}')
            return out_path
        except Exception as e:
            self.log_msg(f'USD export failed: {e}')
            return None

    # Generic selection exports
    def _export_selection_fbx(self, nodes, start_frame, end_frame, out_path):
        if not nodes:
            return None
        try:
            cmds.select(nodes, r=True)
            mel.eval('FBXResetExport;')
            mel.eval('FBXExportInAscii -v false;')
            mel.eval('FBXExportBakeComplexAnimation -v true;')
            mel.eval(f'FBXExportBakeComplexStart -v {start_frame};')
            mel.eval(f'FBXExportBakeComplexEnd -v {end_frame};')
            mel.eval('FBXExportBakeComplexStep -v 1;')
            mel.eval('FBXExportCameras -v true;')
            mel.eval('FBXExportLights -v true;')
            mel.eval('FBXExportSkins -v true;')
            mel.eval('FBXExportShapes -v true;')
            mel.eval('FBXExportConstraints -v true;')
            mel.eval('FBXExportEmbeddedTextures -v false;')
            self._with_temp_no_ontop(lambda: mel.eval(f'FBXExport -f "{out_path}" -s;'))
            self.log_msg(f'FBX exported: {out_path}')
            return out_path
        except Exception as e:
            self.log_msg(f'FBX export failed ({out_path}): {e}')
            return None
        finally:
            try:
                cmds.select(clear=True)
            except Exception:
                pass

    def _export_selection_abc(self, nodes, start_frame, end_frame, out_path):
        if not nodes:
            return None
        try:
            root_flags = ' '.join(f'-root {n}' for n in nodes)
            cmd = f'-frameRange {start_frame} {end_frame} -step 1 -worldSpace {root_flags} -file "{out_path}"'
            mel_cmd = 'AbcExport -j "{}";'.format(cmd.replace('"', '\\"'))
            self._with_temp_no_ontop(lambda: mel.eval(mel_cmd))
            self.log_msg(f'Alembic exported: {out_path}')
            return out_path
        except Exception as e:
            self.log_msg(f'Alembic export failed ({out_path}): {e}')
            return None

    def _gather_light_transforms(self):
        lights = []
        shapes = cmds.ls(lights=True) or []
        for shp in shapes:
            t = cmds.listRelatives(shp, parent=True, fullPath=False) or []
            if t:
                lights.append(t[0])
        # unique preserve order
        seen = set()
        out = []
        for l in lights:
            if l not in seen:
                seen.add(l)
                out.append(l)
        return out

    def _export_lights_and_json(self, start_frame, end_frame, root, do_fbx=True, do_abc=True):
        lights_dir = os.path.join(root, DIR_LIGHTS_EXPORT).replace('\\', '/')
        ensure_dir(lights_dir)
        lights = self._gather_light_transforms()
        if not lights:
            self.log_msg('Lights export: no lights found in scene.')
            return

        # Temp group to keep hierarchy intact for export
        grp_name = 'LIGHTS_EXPORT_GRP'
        if cmds.objExists(grp_name):
            try:
                cmds.delete(grp_name)
            except Exception:
                pass
        parent_map = {}
        try:
            grp = cmds.group(empty=True, name=grp_name)
        except Exception as e:
            self.log_msg(f'Failed to create temp lights group: {e}')
            return
        for l in lights:
            try:
                parent = cmds.listRelatives(l, parent=True, fullPath=False)
                parent_map[l] = parent[0] if parent else None
                cmds.parent(l, grp)
            except Exception as e:
                self.log_msg(f'Failed to parent light {l} to temp group: {e}')

        # Exports
        if do_fbx:
            out_fbx = os.path.join(lights_dir, 'LIGHTS.fbx').replace('\\', '/')
            self._export_selection_fbx([grp], start_frame, end_frame, out_fbx)
        if do_abc:
            out_abc = os.path.join(lights_dir, 'LIGHTS.abc').replace('\\', '/')
            self._export_selection_abc([grp], start_frame, end_frame, out_abc)

        # JSON dump of light properties
        lights_data = []
        for l in lights:
            entry = {'name': l, 'type': None, 'transform': {}, 'attrs': {}}
            try:
                shp = cmds.listRelatives(l, shapes=True, fullPath=False) or []
                if shp:
                    entry['type'] = cmds.nodeType(shp[0])
            except Exception:
                pass
            try:
                entry['transform']['translate'] = cmds.xform(l, q=True, ws=True, t=True)
                entry['transform']['rotate'] = cmds.xform(l, q=True, ws=True, ro=True)
                entry['transform']['scale'] = cmds.xform(l, q=True, r=True, s=True)
            except Exception:
                pass
            # Common attrs
            attr_list = [
                'visibility', 'intensity', 'exposure', 'aiExposure', 'aiRadius',
                'aiSamples', 'aiSpread', 'decayRate', 'emitDiffuse', 'emitSpecular',
                'color', 'coneAngle', 'penumbraAngle', 'dropoff', 'lightAngle',
                'aiColorTemperature', 'shadowColor', 'aiShadowDensity', 'aiShadowColor',
                'aiDiffuse', 'aiSpecular', 'aiVolume'
            ]
            for attr in attr_list:
                plug = f'{l}.{attr}'
                shp_plug = None
                try:
                    shp = cmds.listRelatives(l, shapes=True, fullPath=False) or []
                    if shp:
                        shp_plug = f'{shp[0]}.{attr}'
                except Exception:
                    pass
                for p in (plug, shp_plug):
                    if p and cmds.objExists(p):
                        try:
                            entry['attrs'][attr] = cmds.getAttr(p)
                        except Exception:
                            pass
                        break
            lights_data.append(entry)
        try:
            json_path = os.path.join(lights_dir, 'lights.json').replace('\\', '/')
            with open(json_path, 'w') as jf:
                json.dump(lights_data, jf, indent=2)
            self.log_msg(f'Lights JSON written: {json_path}')
        except Exception as e:
            self.log_msg(f'Failed to write lights JSON: {e}')

        # Restore parenting
        for l in lights:
            try:
                parent = parent_map.get(l)
                if parent:
                    cmds.parent(l, parent)
                else:
                    cmds.parent(l, w=True)
            except Exception as e:
                self.log_msg(f'Failed to restore parent for {l}: {e}')
        try:
            cmds.delete(grp)
        except Exception:
            pass

    # Scene component exports (cameras/lights/geometry separated)
    def export_scene_fbx(self, start_frame, end_frame, out_dir):
        ensure_dir(out_dir)
        default_cams = set(cmds.listCameras(p=True) or [])
        all_cam_shapes = cmds.ls(type='camera') or []
        cam_nodes = []
        for s in all_cam_shapes:
            p = cmds.listRelatives(s, parent=True, fullPath=False) or []
            if p and p[0] not in default_cams:
                cam_nodes.append(p[0])
        for forced_cam in ('LINEUP_CAM', 'LINEUP_CAM_ALT', 'MATCHMOVE_CAM'):
            if forced_cam and cmds.objExists(forced_cam):
                cam_nodes.append(forced_cam)
        cam_nodes = sorted(set(cam_nodes))

        light_nodes = self._gather_light_transforms()

        assemblies = cmds.ls(assemblies=True) or []
        geo_nodes = []
        skip = set(default_cams) | set(cam_nodes) | set(light_nodes)
        for a in assemblies:
            if a in skip:
                continue
            geo_nodes.append(a)

        if not (cam_nodes or light_nodes or geo_nodes):
            self.log_msg('Scene FBX export: no nodes to export.')
            return None

        # Build temp grouped hierarchy: /ROOT/{cameras,lights,geom}
        root_grp = 'ROOT'
        cam_grp = 'cameras'
        light_grp = 'lights'
        geom_grp = 'geom'
        for g in [root_grp, cam_grp, light_grp, geom_grp]:
            if cmds.objExists(g):
                try:
                    cmds.delete(g)
                except Exception:
                    pass
        try:
            cmds.group(empty=True, name=root_grp)
            cmds.group(empty=True, name=cam_grp, parent=root_grp)
            cmds.group(empty=True, name=light_grp, parent=root_grp)
            cmds.group(empty=True, name=geom_grp, parent=root_grp)
        except Exception as e:
            self.log_msg(f'Failed to create temp scene groups: {e}')
            return None

        parent_map = {}
        def _parent_safe(node, target_grp):
            try:
                parent_map[node] = cmds.listRelatives(node, parent=True, fullPath=False) or [None]
                parent_map[node] = parent_map[node][0] if parent_map[node] else None
                cmds.parent(node, target_grp)
            except Exception as e:
                self.log_msg(f'Failed to parent {node} to {target_grp}: {e}')

        for n in cam_nodes:
            _parent_safe(n, cam_grp)
        for n in light_nodes:
            _parent_safe(n, light_grp)
        for n in geo_nodes:
            _parent_safe(n, geom_grp)

        out_path = os.path.join(out_dir, 'SCENE_LINEUP.fbx').replace('\\', '/')
        self._export_selection_fbx([root_grp], start_frame, end_frame, out_path)

        # Restore parenting and cleanup
        for node, parent in parent_map.items():
            try:
                if parent:
                    cmds.parent(node, parent)
                else:
                    cmds.parent(node, w=True)
            except Exception as e:
                self.log_msg(f'Failed to restore parent for {node}: {e}')
        try:
            cmds.delete(root_grp)
        except Exception:
            pass

    def export_scene_abc(self, start_frame, end_frame, out_dir):
        ensure_dir(out_dir)
        default_cams = set(cmds.listCameras(p=True) or [])
        all_cam_shapes = cmds.ls(type='camera') or []
        cam_nodes = []
        for s in all_cam_shapes:
            p = cmds.listRelatives(s, parent=True, fullPath=False) or []
            if p and p[0] not in default_cams:
                cam_nodes.append(p[0])
        for forced_cam in ('LINEUP_CAM', 'LINEUP_CAM_ALT', 'MATCHMOVE_CAM'):
            if forced_cam and cmds.objExists(forced_cam):
                cam_nodes.append(forced_cam)
        cam_nodes = sorted(set(cam_nodes))

        light_nodes = self._gather_light_transforms()

        assemblies = cmds.ls(assemblies=True) or []
        geo_nodes = []
        skip = set(default_cams) | set(cam_nodes) | set(light_nodes)
        for a in assemblies:
            if a in skip:
                continue
            geo_nodes.append(a)

        if not (cam_nodes or light_nodes or geo_nodes):
            self.log_msg('Scene Alembic export: no nodes to export.')
            return None

        root_grp = 'ROOT'
        cam_grp = 'cameras'
        light_grp = 'lights'
        geom_grp = 'geom'
        for g in [root_grp, cam_grp, light_grp, geom_grp]:
            if cmds.objExists(g):
                try:
                    cmds.delete(g)
                except Exception:
                    pass
        try:
            cmds.group(empty=True, name=root_grp)
            cmds.group(empty=True, name=cam_grp, parent=root_grp)
            cmds.group(empty=True, name=light_grp, parent=root_grp)
            cmds.group(empty=True, name=geom_grp, parent=root_grp)
        except Exception as e:
            self.log_msg(f'Failed to create temp scene groups: {e}')
            return None

        parent_map = {}
        def _parent_safe(node, target_grp):
            try:
                parent_map[node] = cmds.listRelatives(node, parent=True, fullPath=False) or [None]
                parent_map[node] = parent_map[node][0] if parent_map[node] else None
                cmds.parent(node, target_grp)
            except Exception as e:
                self.log_msg(f'Failed to parent {node} to {target_grp}: {e}')

        for n in cam_nodes:
            _parent_safe(n, cam_grp)
        for n in light_nodes:
            _parent_safe(n, light_grp)
        for n in geo_nodes:
            _parent_safe(n, geom_grp)

        out_path = os.path.join(out_dir, 'SCENE_LINEUP.abc').replace('\\', '/')
        self._export_selection_abc([root_grp], start_frame, end_frame, out_path)

        for node, parent in parent_map.items():
            try:
                if parent:
                    cmds.parent(node, parent)
                else:
                    cmds.parent(node, w=True)
            except Exception as e:
                self.log_msg(f'Failed to restore parent for {node}: {e}')
        try:
            cmds.delete(root_grp)
        except Exception:
            pass

    def export_only(self):
        if hasattr(self, '_last_build_range'):
            start_frame, end_frame = self._last_build_range
        else:
            start_frame = int(cmds.playbackOptions(q=True, min=True))
            end_frame = int(cmds.playbackOptions(q=True, max=True))
        root = self.current_root()
        if not root:
            QMessageBox.warning(self, 'Root', 'No valid root path.')
            return
        ensure_dir(root)
        self._ensure_root_subdirs(root)
        cam_dir = os.path.join(root, DIR_CAMERA).replace('\\', '/')
        scene_dir = os.path.join(root, DIR_SCENE_EXPORT).replace('\\', '/')

        # Camera-only exports (LINEUP_CAM + ALT + MATCHMOVE if they exist)
        cameras_to_export = []
        lineup_cam, lineup_shape, ok = get_or_create_lineup_camera()
        if ok:
            cameras_to_export.append(('LINEUP_CAM', lineup_cam))
        alt_cam = (cmds.ls('LINEUP_CAM_ALT', type='transform') or [None])[0]
        if alt_cam and cmds.objExists(alt_cam):
            cameras_to_export.append(('LINEUP_CAM_ALT', alt_cam))
        mm_cam = (cmds.ls('MATCHMOVE_CAM', type='transform') or [None])[0]
        if mm_cam and cmds.objExists(mm_cam):
            cameras_to_export.append(('MATCHMOVE_CAM', mm_cam))

        if not cameras_to_export:
            QMessageBox.critical(self, 'Camera error', 'Could not find or create any lineup cameras to export.')
            return

        for cam_name, cam_node in cameras_to_export:
            if self.chk_export_fbx.isChecked():
                self.export_camera_fbx(cam_node, start_frame, end_frame, cam_dir, name=cam_name)
            if self.chk_export_abc.isChecked():
                self.export_camera_abc(cam_node, start_frame, end_frame, cam_dir, name=cam_name)
            if self.chk_export_usd.isChecked():
                self.export_camera_usd(cam_node, start_frame, end_frame, cam_dir, name=cam_name)

        # Lights-only exports and JSON (share toggles with scene exports; default both if either scene toggle is on)
        export_lights_fbx = self.chk_export_scene_fbx.isChecked() or self.chk_export_fbx.isChecked()
        export_lights_abc = self.chk_export_scene_abc.isChecked() or self.chk_export_abc.isChecked()
        if export_lights_fbx or export_lights_abc:
            self._export_lights_and_json(start_frame, end_frame, root, do_fbx=export_lights_fbx, do_abc=export_lights_abc)

        # Scene-level exports
        if self.chk_export_scene_fbx.isChecked():
            self.export_scene_fbx(start_frame, end_frame, scene_dir)
        if self.chk_export_scene_abc.isChecked():
            self.export_scene_abc(start_frame, end_frame, scene_dir)

        QMessageBox.information(self, 'Exports', 'Export finished.')

    # ------------- Build lineup -------------
    def build_lineup(self):
        enforce_scene_imageplanes_display_only_if_current()

        # If matchmove cam is requested, gather all scene cameras (except defaults/LINEUP) with imagePlanes
        matchmove_cam_order = []
        if self.chk_matchmove_cam.isChecked():
            all_cams = list_scene_cameras(include_startup=False)
            for cam in all_cams:
                if cam in ('LINEUP_CAM', 'LINEUP_CAM_ALT') or _is_default_cam(cam):
                    continue
                camS = get_camera_shape(cam)
                ip = find_first_imageplane_on_camera_shape(camS) if camS else None
                if ip:
                    matchmove_cam_order.append(cam)

        if self.chk_clearangle_mode.isChecked():
            if int(self.spin_start.value()) == DEFAULT_START_FRAME:
                self.spin_start.setValue(1201)
            self._refresh_clearangle_camera_list()
            # Import assets for clearangle
            self._import_clearangle_charts()
            self._import_clearangle_lights()
            self._apply_clearangle_lighting_mode()
        cams = [self.listCams.item(i).text() for i in range(self.listCams.count())]
        if not cams:
            QMessageBox.warning(self, 'No cameras', 'Please add cameras to the list.')
            return

        # Pre-check: each camera must have imagePlane with existing file
        missing = []
        for cam in cams:
            camS = get_camera_shape(cam)
            ip = find_first_imageplane_on_camera_shape(camS) if camS else None
            fpath = imageplane_file(ip) if ip else ''
            if not fpath or not os.path.exists(fpath):
                missing.append((cam, ip or '', fpath or '<empty>'))
        if missing:
            lines = ['The following cameras have missing imagePlane files:\n']
            lines += [f' - {cam} [{ip}] -> {f}' for cam, ip, f in missing]
            lines.append('\nPlease fix the paths (use File Path Editor) before creating the lineup.')
            self._with_temp_no_ontop(lambda: QMessageBox.critical(self, 'Missing ImagePlane Files', '\n'.join(lines)))
            return

        base_name = self.line_basename.text().strip()
        if not base_name:
            QMessageBox.warning(self, 'Base name', 'Please enter a base name for the image sequence.')
            return

        start_frame = int(self.spin_start.value())
        root = self.current_root()
        if not root:
            QMessageBox.warning(self, 'Root', 'No valid root path.')
            return
        ensure_dir(root)
        self._ensure_root_subdirs(root)

        img_dir = os.path.join(root, DIR_IMAGEPLANES).replace('\\', '/')
        img_orig_dir = os.path.join(root, DIR_IMAGEPLANES_ORIG).replace('\\', '/')

        append_mode = False
        existing_frames = []
        existing_ext = None
        # Auto-overwrite means replace matching files but do NOT wipe; only wipe when chosen in dialog
        overwrite_action = 'overwrite' if self.chk_overwrite_imageplanes.isChecked() else self._prompt_imageplane_overwrite(img_dir, img_orig_dir, base_name)
        if overwrite_action == 'cancel':
            self.log_msg('User canceled due to existing imageplane files.')
            return
        if overwrite_action == 'wipe':
            removed_img = remove_all_files_in_folder(img_dir)
            removed_orig = remove_all_files_in_folder(img_orig_dir)
            self.log_msg(f'Wipe Folder: removed {removed_img} files from {img_dir}')
            self.log_msg(f'Wipe Folder: removed {removed_orig} files from {img_orig_dir}')
        elif overwrite_action == 'append':
            append_mode = True
            existing_frames, existing_ext = existing_sequence_frames(img_dir, base_name)
            if existing_frames:
                new_start = max(existing_frames) + 1
                if new_start != start_frame:
                    self.log_msg(f'Append mode: shifting start frame from {start_frame} to {new_start} after existing sequence.')
                    start_frame = new_start
                    self.spin_start.setValue(start_frame)
            else:
                self.log_msg('Append mode: no existing sequence found; using requested start frame.')
        else:
            self.log_msg('Overwrite mode: existing files with matching names will be replaced.')
        overwrite_mode = (overwrite_action != 'append')

        manifest_path = self._active_manifest_path(root, base_name)

        camT, camS, ok = get_or_create_lineup_camera()
        if not ok or not camT or not camS:
            QMessageBox.critical(self, 'Camera error', 'Could not create/find LINEUP_CAM.')
            return

        # ALT camera will be created later (after LINEUP_CAM is fully built) via duplicate -rr -un
        alt_camT = None
        alt_camS = None

        # Check for existing keys on main
        existing_keys = False
        try:
            if cmds.keyframe(camT, q=True, kc=True) or cmds.keyframe(camS, q=True, kc=True):
                existing_keys = True
        except Exception:
            pass
        if existing_keys:
            reply = self._with_temp_no_ontop(lambda: QMessageBox.question(
                self, 'Overwrite keys?',
                'LINEUP_CAM has animation. Overwrite?',
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No))
            if reply != QMessageBox.Yes:
                self.log_msg('Canceled. LINEUP_CAM unchanged.')
                return

        # Clear keys on main and ALT (ALT will be overwritten with copyKey later)
        try:
            cmds.cutKey(camT, clear=True)
            cmds.cutKey(camS, clear=True)
        except Exception:
            pass

        # Scale factor applied directly to sampled positions (no temp grouping)
        scale_factor = 1.0

        # Copy originals to imageplanes_orig and rewire (if not already there)
        ensure_dir(img_orig_dir)
        mm_orig_dir = os.path.join(root, MM_DIR).replace('\\', '/')
        ensure_dir(mm_orig_dir)
        # Build list of target imagePlanes (no camera filtering; only skip if already lives in dest)
        get_ips = list_imageplanes_on_camera_shape if 'list_imageplanes_on_camera_shape' in globals() else list_imageplane_on_camera_shape
        target_ips = []
        if self.chk_copy_all_imageplanes.isChecked():
            target_ips = list_scene_imageplanes()
        else:
            for cam in cams:
                camShape = get_camera_shape(cam)
                for ip in get_ips(camShape):
                    target_ips.append(ip)
        # unique order preserved
        seen_ips = set()
        target_ips_ordered = []
        for ip in target_ips:
            if ip not in seen_ips:
                seen_ips.add(ip)
                target_ips_ordered.append(ip)

        dest_abs = os.path.abspath(img_orig_dir)
        mm_copied = []
        for ip in target_ips_ordered:
            src_path = imageplane_file(ip) if ip else ''
            if not (ip and src_path and os.path.exists(src_path)):
                continue
            try:
                if os.path.commonpath([dest_abs, os.path.abspath(src_path)]) == dest_abs:
                    # Already in imageplanes_orig; leave path as is
                    continue
            except Exception:
                pass
            self._copy_ip_to_orig(ip, src_path, img_orig_dir, append_mode=append_mode, overwrite_mode=overwrite_mode)

        # Copy matchmove imagePlanes to mm_orig_dir and rewire (and sequence for MATCHMOVE_CAM)
        if self.chk_matchmove_cam.isChecked() and matchmove_cam_order:
            dest_mm_abs = os.path.abspath(mm_orig_dir)
            mm_frame = start_frame
            mm_base = base_name + '_mm'
            for cam in matchmove_cam_order:
                camShape = get_camera_shape(cam)
                for ip in get_ips(camShape):
                    src_path = imageplane_file(ip) if ip else ''
                    if not (ip and src_path and os.path.exists(src_path)):
                        continue
                    try:
                        if os.path.commonpath([dest_mm_abs, os.path.abspath(src_path)]) == dest_mm_abs:
                            # already in mm orig; still record for sequence if matches pattern
                            pass
                    except Exception:
                        pass
                    comp = detect_sequence_components(src_path)
                    ext = comp['ext'] if comp else os.path.splitext(src_path)[1]
                    dst = os.path.join(mm_orig_dir, f'{mm_base}.{mm_frame:04d}{ext}').replace('\\', '/')
                    try:
                        if not os.path.exists(dst):
                            shutil.copy2(src_path, dst)
                        mm_copied.append((dst, mm_frame, ext))
                        self.log_msg(f'Matchmove IP copied: {ip} -> {dst}')
                    except Exception as e:
                        self.log_msg(f'Failed to copy/rewire matchmove IP {ip}: {e}')
                    mm_frame += 1

        # Build LINEUP_CAM animation and copy imagePlane files to sequence
        current_frame = start_frame
        copied_files = []
        any_ext = existing_ext or None
        manifest_entries = []
        scene_file = scene_path()
        user = self.line_username.text().strip() or getpass.getuser()
        now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        total_steps = len(cams) + (len(matchmove_cam_order) if self.chk_matchmove_cam.isChecked() else 0)
        progress = QProgressDialog('Creating lineup...', 'Cancel', 0, total_steps, self)
        progress.setWindowTitle('Building Lineup')
        progress.setWindowModality(QtCore.Qt.WindowModal)
        progress.setMinimumDuration(0)
        progress.show()

        for idx, src_cam in enumerate(cams):
            if progress.wasCanceled():
                self.log_msg('Build canceled by user.')
                break

            camShape = get_camera_shape(src_cam)
            ip = find_first_imageplane_on_camera_shape(camShape) if camShape else None
            src_path = imageplane_file(ip) if ip else ''
            src_basename = os.path.splitext(os.path.basename(src_path))[0] if src_path else None

            try:
                # World-space transform
                pos = cmds.xform(src_cam, q=True, ws=True, t=True)
                if pos and scale_factor != 1.0:
                    pos = [p * scale_factor for p in pos]
                rot = cmds.xform(src_cam, q=True, ws=True, ro=True)

                fl = cmds.getAttr(camShape + '.focalLength') if camShape and cmds.objExists(camShape + '.focalLength') else None
                hfa = cmds.getAttr(camShape + '.horizontalFilmAperture') if camShape and cmds.objExists(camShape + '.horizontalFilmAperture') else None
                vfa = cmds.getAttr(camShape + '.verticalFilmAperture') if camShape and cmds.objExists(camShape + '.verticalFilmAperture') else None
                hoa = cmds.getAttr(camShape + '.horizontalFilmOffset') if camShape and cmds.objExists(camShape + '.horizontalFilmOffset') else None
                voa = cmds.getAttr(camShape + '.verticalFilmOffset') if camShape and cmds.objExists(camShape + '.verticalFilmOffset') else None
                lsr = cmds.getAttr(camShape + '.lensSqueezeRatio') if camShape and cmds.objExists(camShape + '.lensSqueezeRatio') else None
                filmFit = cmds.getAttr(camShape + '.filmFit') if camShape and cmds.objExists(camShape + '.filmFit') else None
                nearC = cmds.getAttr(camShape + '.nearClipPlane') if camShape and cmds.objExists(camShape + '.nearClipPlane') else None
                farC = cmds.getAttr(camShape + '.farClipPlane') if camShape and cmds.objExists(camShape + '.farClipPlane') else None

                # Main lineup camera pose and attrs
                cmds.xform(camT, ws=True, t=pos)
                cmds.xform(camT, ws=True, ro=rot)
                if fl is not None: cmds.setAttr(camS + '.focalLength', fl)
                if hfa is not None: cmds.setAttr(camS + '.horizontalFilmAperture', hfa)
                if vfa is not None: cmds.setAttr(camS + '.verticalFilmAperture', vfa)
                if hoa is not None and cmds.objExists(camS + '.horizontalFilmOffset'): cmds.setAttr(camS + '.horizontalFilmOffset', hoa)
                if voa is not None and cmds.objExists(camS + '.verticalFilmOffset'): cmds.setAttr(camS + '.verticalFilmOffset', voa)
                if lsr is not None and cmds.objExists(camS + '.lensSqueezeRatio'): cmds.setAttr(camS + '.lensSqueezeRatio', lsr)
                if filmFit is not None and cmds.objExists(camS + '.filmFit'): cmds.setAttr(camS + '.filmFit', filmFit)
                if nearC is not None: cmds.setAttr(camS + '.nearClipPlane', nearC)
                if farC is not None: cmds.setAttr(camS + '.farClipPlane', farC)

                cmds.setKeyframe(camT, t=current_frame)
                cmds.setKeyframe(camS, t=current_frame)

                self.log_msg(f'Keyed LINEUP_CAM at frame {current_frame} from {src_cam}')
            except Exception as e:
                self.log_msg(f'Failed to key from {src_cam}: {e}')

            copied_dst = None
            ext_used = None
            if src_path and os.path.exists(src_path):
                comp = detect_sequence_components(src_path)
                ext = comp['ext'] if comp else os.path.splitext(src_path)[1]
                ext_used = ext
                dst_name = f'{base_name}.{current_frame:04d}{ext}'
                dst_path = os.path.join(img_dir, dst_name).replace('\\', '/')
                try:
                    ensure_dir(img_dir)
                    if append_mode and os.path.exists(dst_path):
                        copied_dst = dst_path
                        self.log_msg(f'Append mode: keeping existing lineup file {dst_path}')
                    else:
                        shutil.copy2(src_path, dst_path)
                        copied_dst = dst_path
                        self.log_msg(f'Copied imagePlane from {src_cam} -> {dst_path}')
                    copied_files.append((dst_path, current_frame))
                except Exception as e:
                    self.log_msg(f'Copy failed for {src_path} -> {dst_path}: {e}')
            else:
                self.log_msg(f'Unexpected missing file at build time: {src_cam} -> {src_path}')

            any_ext = any_ext or ext_used
            manifest_entries.append({
                'order_index': idx,
                'lineup_frame': current_frame,
                'camera_name': src_cam,
                'image_plane': {
                    'node': ip,
                    'source_file': src_path,
                    'basename': src_basename,
                    'copied_file': copied_dst
                }
            })
            current_frame += 1
            progress.setValue(idx + 1)
            QtWidgets.QApplication.processEvents()

        progress.close()

        # Build MATCHMOVE_CAM if requested
        if self.chk_matchmove_cam.isChecked() and matchmove_cam_order:
            mm_camT = cmds.ls('MATCHMOVE_CAM', type='transform') or []
            if mm_camT:
                try:
                    cmds.delete(mm_camT)
                except Exception:
                    pass
            try:
                mm_camT, mm_camS_ok = cmds.camera(n='MATCHMOVE_CAM')
                mm_camT = cmds.rename(mm_camT, 'MATCHMOVE_CAM')
                mm_camS = cmds.listRelatives(mm_camT, shapes=True)[0]
            except Exception as e:
                self.log_msg(f'Failed to create MATCHMOVE_CAM: {e}')
                mm_camT = None
                mm_camS = None
            mm_frame = start_frame
            for idx, src_cam in enumerate(matchmove_cam_order):
                try:
                    camShape = get_camera_shape(src_cam)
                    pos = cmds.xform(src_cam, q=True, ws=True, t=True)
                    if pos and scale_factor != 1.0:
                        pos = [p * scale_factor for p in pos]
                    rot = cmds.xform(src_cam, q=True, ws=True, ro=True)
                    fl = cmds.getAttr(camShape + '.focalLength') if camShape and cmds.objExists(camShape + '.focalLength') else None
                    hfa = cmds.getAttr(camShape + '.horizontalFilmAperture') if camShape and cmds.objExists(camShape + '.horizontalFilmAperture') else None
                    vfa = cmds.getAttr(camShape + '.verticalFilmAperture') if camShape and cmds.objExists(camShape + '.verticalFilmAperture') else None
                    cmds.xform(mm_camT, ws=True, t=pos)
                    cmds.xform(mm_camT, ws=True, ro=rot)
                    if fl is not None: cmds.setAttr(mm_camS + '.focalLength', fl)
                    if hfa is not None: cmds.setAttr(mm_camS + '.horizontalFilmAperture', hfa)
                    if vfa is not None: cmds.setAttr(mm_camS + '.verticalFilmAperture', vfa)
                    cmds.setKeyframe(mm_camT, t=mm_frame)
                    cmds.setKeyframe(mm_camS, t=mm_frame)
                    mm_frame += 1
                except Exception as e:
                    self.log_msg(f'Matchmove key failed from {src_cam}: {e}')
            # Assign matchmove imagePlane sequence
            if mm_copied:
                mm_ip = get_or_create_ip_on_camera(mm_camT)
                mm_ip_shape = mm_ip
                if mm_ip and not mm_ip.endswith('Shape'):
                    shapes = cmds.listRelatives(mm_ip, shapes=True, fullPath=True) or []
                    if shapes:
                        mm_ip_shape = shapes[0]
                first_frame = min(f for _, f, _ in mm_copied)
                ext = mm_copied[0][2] if mm_copied else '.exr'
                first_file = os.path.join(mm_orig_dir, f'{mm_base}.{first_frame:04d}{ext}').replace('\\', '/')
                try:
                    cmds.setAttr(mm_ip_shape + '.imageName', first_file, type='string')
                    if cmds.objExists(mm_ip_shape + '.useFrameExtension'):
                        cmds.setAttr(mm_ip_shape + '.useFrameExtension', 1)
                    if cmds.objExists(mm_ip_shape + '.depth'):
                        cmds.setAttr(mm_ip_shape + '.depth', 1000)
                    set_imageplane_display_only_if_current(mm_ip_shape)
                    self.log_msg(f'MATCHMOVE_CAM imagePlane assigned to {first_file}')
                except Exception as e:
                    self.log_msg(f'Failed to assign MATCHMOVE_CAM imagePlane: {e}')


        first_file = None
        if copied_files or (append_mode and existing_frames):
            ip_lineup = get_or_create_ip_on_camera(camT)
            ip_shape = ip_lineup
            if not ip_lineup.endswith('Shape'):
                shapes = cmds.listRelatives(ip_lineup, shapes=True, fullPath=True) or []
                if shapes:
                    ip_shape = shapes[0]
            if copied_files:
                first_frame = min(f for _, f in copied_files)
            else:
                first_frame = existing_frames[0]
            ext = any_ext or existing_ext or '.exr'
            first_file = os.path.join(img_dir, f'{base_name}.{first_frame:04d}{ext}').replace('\\', '/')
            try:
                cmds.setAttr(ip_shape + '.imageName', first_file, type='string')
                if cmds.objExists(ip_shape + '.useFrameExtension'):
                    cmds.setAttr(ip_shape + '.useFrameExtension', 1)
                if cmds.objExists(ip_shape + '.depth'):
                    cmds.setAttr(ip_shape + '.depth', 1000)
                set_imageplane_display_only_if_current(ip_shape)
                self.log_msg(f'Assigned lineup imagePlane to sequence starting at {first_file}')
            except Exception as e:
                self.log_msg(f'Failed to assign image sequence to LINEUP_CAM imagePlane: {e}')
        else:
            self.log_msg('No copied files — lineup imagePlane not assigned.')

        try:
            cmds.playbackOptions(minTime=start_frame, maxTime=current_frame - 1)
            cmds.currentTime(start_frame)
        except Exception:
            pass

        self._last_build_range = (start_frame, current_frame - 1)
        end_frame = current_frame - 1

        # Manifest with UI state for recall
        manifest = {
            'created_at': now,
            'user': user,
            'show_code': self.line_show.text().strip(),
            'shot': 'SHR_shr_rsrc',
            'asset': self.combo_asset.currentText().strip(),
            'maya_scene': scene_file,
            'project_root': root,
            'lineup_camera': 'LINEUP_CAM',
            'lineup': {
                'start_frame': start_frame,
                'end_frame': end_frame,
                'base_name': base_name,
                'extension': (any_ext or '.exr')
            },
            'entries': manifest_entries,
            'exports': {
                'camera_dir': os.path.join(root, DIR_CAMERA).replace('\\', '/'),
                'notes': 'Use Export Camera / Scene Data to write FBX/ABC/USD.'
            },
            'ui_state': {
                'project': self.combo_project.currentText().strip(),
                'asset': self.combo_asset.currentText().strip(),
                'custom_root_enabled': self.chk_custom_root.isChecked(),
                'custom_root_path': self.line_custom_root.text().strip(),
                'base_name': base_name,
                'manifest_name': '',  # manifest is auto-computed unless custom is provided
                'start_frame': start_frame,
                'overwrite_imageplanes': self.chk_overwrite_imageplanes.isChecked(),
                'copy_all_imageplanes': self.chk_copy_all_imageplanes.isChecked(),
                'import_charts': self.chk_import_charts.isChecked(),
                'animate_lights': self.chk_animate_lights.isChecked(),
                'matchmove_cam': self.chk_matchmove_cam.isChecked(),
                'clearangle_mode': self.chk_clearangle_mode.isChecked(),
                'clearangle_preset': self.combo_ca_preset.currentText(),
                'create_alt': self.chk_create_alt_cam.isChecked(),
                'alt_aspect': float(self.spin_alt_aspect.value()),
                'camera_list': cams
            }
        }

        if self.chk_clearangle_mode.isChecked():
            cfg = self._load_clearangle_config(self.combo_ca_preset.currentText()) or {}
            manifest['clearangle'] = {
                'preset': self.combo_ca_preset.currentText(),
                'targets': cfg.get('targets', []),
                'mode': cfg.get('mode'),
                'resolved_cameras': cams
            }
        try:
            with open(self._manifest_path(root, base_name), 'w') as f:
                json.dump(manifest, f, indent=2)
            manifest_path = self._manifest_path(root, base_name)
            self.log_msg(f'Manifest written: {manifest_path}')
        except Exception as e:
            manifest_path = ''
            self.log_msg(f'Failed to write manifest JSON: {e}')

        self._save_maya_in_root(root)

        # Set render resolution and range from first lineup frame using oiiotool
        if first_file and os.path.exists(first_file):
            oiiotool = self.line_oiio.text().strip() or DEFAULT_OIIOTOOL
            if os.path.exists(oiiotool):
                w, h = self._get_image_size_oiiotool(oiiotool, first_file)
                if w and h:
                    try:
                        cmds.setAttr('defaultResolution.width', int(w))
                        cmds.setAttr('defaultResolution.height', int(h))
                        cmds.setAttr('defaultResolution.deviceAspectRatio', float(w) / float(h))
                        cmds.setAttr('defaultResolution.pixelAspect', 1.0)
                        cmds.setAttr('defaultRenderGlobals.startFrame', float(start_frame))
                        cmds.setAttr('defaultRenderGlobals.endFrame', float(end_frame))
                        self.log_msg(f'Set render resolution to {w} x {h}, frames {start_frame}-{end_frame}')
                    except Exception as e:
                        self.log_msg(f'Failed to set render resolution / range: {e}')
                else:
                    self.log_msg('Could not read image resolution from oiiotool; render resolution unchanged.')
            else:
                self.log_msg(f'oiiotool not found at {oiiotool}; cannot set render resolution.')
        else:
            self.log_msg('No first_file for lineup; render resolution unchanged.')

        # Configure ALT camera:
        #   - duplicate LINEUP_CAM animation (transform + shape) using duplicate -rr -un
        #   - adjust horizontalFilmAperture per frame to match new aspect
        if self.chk_create_alt_cam.isChecked():
            try:
                # Delete any existing ALT to ensure a clean duplicate
                if cmds.objExists('LINEUP_CAM_ALT'):
                    try:
                        cmds.delete('LINEUP_CAM_ALT')
                        self.log_msg('Deleted existing LINEUP_CAM_ALT before creating a new duplicate.')
                    except Exception as e:
                        self.log_msg(f'Could not delete existing LINEUP_CAM_ALT: {e}')

                # Duplicate LINEUP_CAM with upstream animation (equivalent to "duplicate -rr -un")
                alt_camT = None
                alt_camS = None
                try:
                    dup_nodes = cmds.duplicate(camT, rr=True, un=True)
                    if dup_nodes:
                        alt_camT = cmds.rename(dup_nodes[0], 'LINEUP_CAM_ALT')
                        alt_camS = get_camera_shape(alt_camT)
                        self.log_msg('Created LINEUP_CAM_ALT via duplicate -rr -un (animation + shape).')
                except Exception as e:
                    self.log_msg(f'Failed to duplicate LINEUP_CAM to ALT: {e}')

                if not (alt_camT and alt_camS):
                    self.log_msg('LINEUP_CAM_ALT could not be created; skipping ALT configuration.')
                    raise RuntimeError('ALT duplicate failed')

                has_frame_range = end_frame >= start_frame

                # Attach same image sequence to ALT camera
                if first_file:
                    ip_alt = get_or_create_ip_on_camera(alt_camT)
                    ip_alt_shape = ip_alt
                    if ip_alt and not ip_alt.endswith('Shape'):
                        shapes = cmds.listRelatives(ip_alt, shapes=True, fullPath=True) or []
                        if shapes:
                            ip_alt_shape = shapes[0]

                    if ip_alt_shape:
                        try:
                            cmds.setAttr(ip_alt_shape + '.imageName', first_file, type='string')
                            if cmds.objExists(ip_alt_shape + '.useFrameExtension'):
                                cmds.setAttr(ip_alt_shape + '.useFrameExtension', 1)
                            if cmds.objExists(ip_alt_shape + '.fit'):
                                cmds.setAttr(ip_alt_shape + '.fit', 2)  # vertical fit
                            set_imageplane_display_only_if_current(ip_alt_shape)
                        except Exception as e:
                            self.log_msg(f'Failed to configure LINEUP_CAM_ALT imagePlane: {e}')

                # Adjust film aperture per frame using original aspect ratio
                alt_aspect = float(self.spin_alt_aspect.value())
                if (has_frame_range and
                    cmds.objExists(camS + '.verticalFilmAperture') and
                    cmds.objExists(camS + '.horizontalFilmAperture') and
                    cmds.objExists(alt_camS + '.verticalFilmAperture') and
                    cmds.objExists(alt_camS + '.horizontalFilmAperture')):
                    key_times = set()
                    try:
                        kt = cmds.keyframe(camS, attribute='horizontalFilmAperture', q=True, tc=True) or []
                        key_times.update(kt)
                    except Exception:
                        pass
                    try:
                        kt = cmds.keyframe(camS, attribute='verticalFilmAperture', q=True, tc=True) or []
                        key_times.update(kt)
                    except Exception:
                        pass
                    if not key_times:
                        key_times = set(range(start_frame, end_frame + 1))

                    for t in sorted(key_times):
                        try:
                            vfa = cmds.getAttr(camS + '.verticalFilmAperture', time=t)
                        except Exception:
                            vfa = cmds.getAttr(camS + '.verticalFilmAperture')
                        try:
                            hfa = cmds.getAttr(camS + '.horizontalFilmAperture', time=t)
                        except Exception:
                            hfa = cmds.getAttr(camS + '.horizontalFilmAperture')

                        # Original aspect per frame/key
                        if vfa == 0:
                            orig_aspect = alt_aspect
                        else:
                            orig_aspect = float(hfa) / float(vfa)

                        # Scale factor from original aspect to new aspect
                        if orig_aspect == 0:
                            scale_factor = 1.0
                        else:
                            scale_factor = alt_aspect / orig_aspect

                        new_hfa = hfa * scale_factor

                        try:
                            cmds.setAttr(alt_camS + '.verticalFilmAperture', vfa)
                            cmds.setAttr(alt_camS + '.horizontalFilmAperture', new_hfa)
                            cmds.setKeyframe(alt_camS, attribute='verticalFilmAperture', t=t, value=vfa)
                            cmds.setKeyframe(alt_camS, attribute='horizontalFilmAperture', t=t, value=new_hfa)
                        except Exception as e:
                            self.log_msg(f'Failed to set film aperture on ALT at frame {t}: {e}')

                    self.log_msg(
                        f'Adjusted LINEUP_CAM_ALT film gate for aspect {alt_aspect} '
                        f'over frames {start_frame}-{end_frame}.'
                    )
                elif not has_frame_range:
                    self.log_msg('No frame range found; skipped film gate adjustment on LINEUP_CAM_ALT.')

                # Ensure film gate visible across the range
                try:
                    if cmds.objExists(alt_camS + '.displayFilmGate'):
                        cmds.setAttr(alt_camS + '.displayFilmGate', 1)
                        if has_frame_range:
                            cmds.setKeyframe(alt_camS, attribute='displayFilmGate', t=start_frame)
                            cmds.setKeyframe(alt_camS, attribute='displayFilmGate', t=end_frame)
                except Exception as e:
                    self.log_msg(f'Failed to configure displayFilmGate on LINEUP_CAM_ALT: {e}')

                self.log_msg('LINEUP_CAM_ALT animation duplicated from LINEUP_CAM and film gate adjusted with per-frame aspect logic.')
            except Exception as e:
                self.log_msg(f'Failed to finalize LINEUP_CAM_ALT: {e}')

        # Renderable cameras: only LINEUP_CAM + LINEUP_CAM_ALT
        lineup_cams = ['LINEUP_CAM']
        if self.chk_create_alt_cam.isChecked() and alt_camT:
            lineup_cams.append('LINEUP_CAM_ALT')

        for camShape in cmds.ls(type='camera') or []:
            parent = cmds.listRelatives(camShape, parent=True, fullPath=False) or []
            is_lineup = bool(parent and parent[0] in lineup_cams)
            try:
                cmds.setAttr(camShape + '.renderable', 1 if is_lineup else 0)
            except Exception:
                pass

        self.spin_start.setValue(start_frame)

        # Nuke script from template aligned to new lineup
        try:
            # Keep optional blocks during build; they'll be pruned after RAW processing
            self._write_nuke_script(root, manifest, strip_optional=False)
        except Exception as e:
            self.log_msg(f'Failed to write Nuke script after build: {e}')

        QMessageBox.information(
            self,
            'Done',
            'Lineup built, manifest written, scene saved if needed.\n'
            'LINEUP_CAM + LINEUP_CAM_ALT are renderable-only cameras.\n'
            'ALT cam duplicates LINEUP_CAM animation with per-frame film gate adjustment.\n'
            'Render res & Nuke template are aligned to this lineup.'
        )

    def _save_maya_in_root(self, root):
        maya_dir = os.path.join(root, DIR_MAYA).replace('\\', '/')
        ensure_dir(maya_dir)
        scene = scene_path()
        if scene and os.path.basename(scene).lower().find('untitled') == -1:
            self.log_msg(f'Scene already saved as "{scene}". Skipping auto-save.')
            return
        if scene:
            base = os.path.splitext(os.path.basename(scene))[0]
        else:
            base = f"{self.line_show.text().strip()}_{self.combo_asset.currentText().strip()}_lineup"
        ts = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
        out_path = os.path.join(maya_dir, f'{base}_{ts}.ma').replace('\\', '/')
        try:
            cmds.file(rename=out_path)
            cmds.file(save=True, type='mayaAscii')
            self.log_msg(f'Saved Maya scene: {out_path}')
        except Exception as e:
            self.log_msg(f'Failed to save Maya scene: {e}')

    # ------------- Nuke script writer -------------
    def _write_nuke_script(self, root, manifest, strip_optional=True):
        """Write Nuke script using the external template and manifest values."""
        nuke_dir = os.path.join(root, DIR_NUKE).replace('\\', '/')
        ensure_dir(nuke_dir)

        show = manifest.get('show_code') or os.getenv('SCL_SHOW_CODE') or 'PROJECT'
        asset = manifest.get('asset') or 'ASSET'
        shot = manifest.get('shot') or 'SHOT'
        lineup = manifest.get('lineup', {}) or {}
        start_frame = int(lineup.get('start_frame', lineup.get('frame_start', DEFAULT_START_FRAME)))
        end_frame = int(lineup.get('end_frame', lineup.get('frame_end', start_frame)))

        # Fallback if manifest is missing frame range but has entries
        if manifest.get('entries') and (end_frame is None or end_frame == start_frame):
            try:
                frames = [int(e.get('lineup_frame', 0)) for e in manifest.get('entries', [])]
                if frames:
                    start_frame = min(frames)
                    end_frame = max(frames)
            except Exception:
                pass

        if not os.path.exists(NUKE_TEMPLATE_PATH):
            self.log_msg(f'Nuke template not found: {NUKE_TEMPLATE_PATH}')
            return
        try:
            nk_text = Path(NUKE_TEMPLATE_PATH).read_text()
        except Exception as e:
            self.log_msg(f'Failed to read Nuke template: {e}')
            return

        # Placeholder substitution based on template keywords
        subs = {
            'PROJECT': show,
            'ASSET': asset,
            'FIRST_FRAME': str(start_frame),
            'LAST_FRAME': str(end_frame),
        }
        for k, v in subs.items():
            nk_text = nk_text.replace(k, v)

        # Shot replacements (if present in template)
        nk_text = re.sub(r'(?m)^ shot\s+\S+', f' shot {shot}', nk_text)
        nk_text = re.sub(r'(?m)^ shotEnv\s+\S+', f' shotEnv {shot}', nk_text)
        nk_text = re.sub(r'/scenes/[^/]+/', f'/scenes/{shot}/', nk_text)

        nk_name = f"{show}_{asset}_lineup_io.nk"
        nk_path = os.path.join(nuke_dir, nk_name).replace('\\', '/')
        try:
            Path(nk_path).write_text(nk_text)
            self.log_msg(f'Wrote Nuke script from template: {nk_path}')
        except Exception as e:
            self.log_msg(f'Failed to write Nuke script: {e}')

    # ------------- RAW helpers & processing (unchanged core behaviour) -------------
    def pick_und_manifest(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Choose manifest JSON', '', 'JSON (*.json)')
        if path:
            self.line_custom_manifest.setText(path.replace('\\', '/'))
            self.chk_custom_manifest.setChecked(True)

    def pick_und_root(self):
        pass

    def open_und_root(self):
        p = self.current_root() or os.getcwd()
        p_forward = p.replace('\\', '/')
        if not os.path.isdir(p):
            self._with_temp_no_ontop(lambda: QMessageBox.warning(self, 'Folder', f'Path does not exist:\n{p_forward}'))
            return
        try:
            if os.name == 'nt':
                win_path = os.path.normpath(p)
                os.startfile(win_path)
            elif sys.platform == 'darwin':
                run_silent(['open', p_forward])
            else:
                run_silent(['xdg-open', p_forward])
            self.log_msg(f'Opened folder: {p_forward}')
        except Exception as e:
            self.log_msg(f'Failed to open folder {p_forward}: {e}')
            self._with_temp_no_ontop(lambda: QMessageBox.warning(self, 'Open Folder', f'Could not open:\n{p_forward}\n\n{e}'))

    def pick_src_st(self):
        p = QFileDialog.getExistingDirectory(self, 'Choose ST maps source folder')
        if p:
            self.line_src_st.setText(p.replace('\\', '/'))

    def pick_src_raw(self):
        p = QFileDialog.getExistingDirectory(self, 'Choose Camera RAW source folder')
        if p:
            self.line_src_raw.setText(p.replace('\\', '/'))

    def pick_src_grey(self):
        p = QFileDialog.getExistingDirectory(self, 'Choose Grey RAW source folder')
        if p:
            self.line_src_grey.setText(p.replace('\\', '/'))

    def pick_src_chart(self):
        p = QFileDialog.getExistingDirectory(self, 'Choose Chart RAW folder')
        if p:
            self.line_src_chart.setText(p.replace('\\', '/'))

    def pick_src_chrome(self):
        p = QFileDialog.getExistingDirectory(self, 'Choose Chrome RAW folder')
        if p:
            self.line_src_chrome.setText(p.replace('\\', '/'))

    def pick_oiiotool(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Locate oiiotool', DEFAULT_OIIOTOOL, 'Executable (*)')
        if path:
            self.line_oiio.setText(path.replace('\\', '/'))

    def _read_manifest(self, path):
        try:
            with open(path, 'r') as f:
                return json.load(f)
        except Exception as e:
            self.log_msg(f'Failed to read manifest: {e}')
            return None

    def _scan_folder_for(self, folder, exts):
        out = []
        if not folder or not os.path.isdir(folder):
            return out
        for root_dir, _, files in os.walk(folder):
            for f in files:
                if os.path.splitext(f)[1].lower() in exts:
                    out.append(os.path.join(root_dir, f))
        return sorted(set(out))

    def _get_image_size_oiiotool(self, oiiotool, image_path):
        try:
            proc = run_silent(
                [oiiotool, image_path, '--info', '-v'],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            txt = proc.stdout or ''
            m = re.search(r'Resolution:\s*(\d+)\s*x\s*(\d+)', txt)
            if not m:
                m = re.search(r'(\d+)\s*x\s*(\d+)', txt)
            if m:
                return int(m.group(1)), int(m.group(2))
        except Exception as e:
            self.log_msg(f'Failed to query size for {image_path}: {e}')
        return None, None

    def _prepare_stmap_for_warp(self, oiiotool, st_path, target_w, target_h):
        if not st_path or not os.path.exists(st_path):
            return None, 0, 1
        mode = self.combo_st_mode.currentText()
        custom = self.line_st_custom.text().strip()
        chan_s, chan_t = 0, 1
        name_s = name_t = None
        use_names = False
        if mode.startswith('RGB'):
            chan_s, chan_t = 0, 1
        elif mode.startswith('UV'):
            name_s, name_t = 'u', 'v'
            use_names = True
        else:
            if custom:
                parts = [p.strip() for p in custom.replace('/', ',').split(',') if p.strip()]
                if len(parts) >= 2:
                    if parts[0].isdigit() and parts[1].isdigit():
                        chan_s, chan_t = int(parts[0]), int(parts[1])
                    else:
                        name_s, name_t = parts[0], parts[1]
                        use_names = True
        st_cur = st_path
        if use_names and name_s and name_t:
            base, ext = os.path.splitext(os.path.basename(st_path))
            st_named = os.path.join(os.path.dirname(st_path), f'{base}_{name_s}{name_t}{ext}').replace('\\', '/')
            if not os.path.exists(st_named):
                cmd = [oiiotool, st_cur, '--ch', f'{name_s},{name_t}', '-o', st_named]
                self.log_msg(f'oiiotool (select ST channels): {" ".join(cmd)}')
                try:
                    proc = run_silent(cmd)
                    if proc.returncode == 0:
                        st_cur = st_named
                        chan_s, chan_t = 0, 1
                    else:
                        self.log_msg(f'oiiotool --ch failed (code {proc.returncode}).')
                except Exception as e:
                    self.log_msg(f'oiiotool --ch error: {e}')
        if target_w and target_h:
            base, ext = os.path.splitext(os.path.basename(st_cur))
            st_resized = os.path.join(os.path.dirname(st_cur), f'{base}_resized_{target_w}x{target_h}{ext}').replace('\\', '/')
            if not os.path.exists(st_resized):
                cmd = [oiiotool, st_cur, '--resize', f'{target_w}x{target_h}', '-o', st_resized]
                self.log_msg(f'oiiotool (resize ST): {" ".join(cmd)}')
                try:
                    proc = run_silent(cmd)
                    if proc.returncode == 0:
                        st_cur = st_resized
                    else:
                        self.log_msg(f'oiiotool resize failed (code {proc.returncode}).')
                except Exception as e:
                    self.log_msg(f'oiiotool resize error: {e}')
            else:
                st_cur = st_resized
        return st_cur, chan_s, chan_t

    def _run_oiiotool_raw_to_acescg(self, oiiotool, raw_path, out_exr_path, highlight_mode='0', debug=False):
        cmd = [
            oiiotool,
            '-iconfig', 'raw:ColorSpace', 'ACES',
            '-iconfig', 'raw:HighlightMode', str(highlight_mode),
            '-iconfig', 'raw:use_camera_wb', '1',
            '-i', raw_path
        ]
        if debug:
            cmd.append('--debug')
        cmd += [
            '--colorconvert', 'ACES - ACES2065-1', 'ACES - ACEScg',
            '--compression', 'zips',
            '-d', 'half',
            '-o', out_exr_path
        ]
        try:
            self.log_msg(f'oiiotool RAW->ACEScg: {" ".join(cmd)}')
            proc = run_silent(cmd)
            return proc.returncode, '', ''
        except Exception as e:
            return 1, '', f'Failed to run oiiotool: {e}'

    def _run_oiiotool_stwarp(self, oiiotool, input_exr, stmap_exr, output_exr, chan_s=0, chan_t=1, debug=False):
        cmd = [oiiotool]
        if debug:
            cmd.append('--debug')
        cmd += [
            input_exr,
            stmap_exr,
            f'--st_warp:chan_s={chan_s}:chan_t={chan_t}:flip_t=1',
            '--compression', 'zips',
            '-d', 'half',
            '-o', output_exr
        ]
        self.log_msg(f'oiiotool ST-warp: {" ".join(cmd)}')
        try:
            proc = run_silent(cmd)
            if proc.returncode != 0:
                return False, f'oiiotool st_warp failed (code {proc.returncode})'
            return True, None
        except Exception as e:
            return False, f'Failed to run oiiotool st_warp: {e}'

    def _validate_optional_family(self, label, src_dir):
        if not src_dir:
            return True, []
        if not os.path.isdir(src_dir):
            self._with_temp_no_ontop(lambda: QMessageBox.warning(self, f'{label} folder', f'{label} path is invalid:\n{src_dir}'))
            return False, []
        files = self._scan_folder_for(src_dir, RAW_EXTS)
        if not files:
            self._with_temp_no_ontop(lambda: QMessageBox.warning(self, f'{label} files', f'No RAW files found in {label} path:\n{src_dir}'))
            return False, []
        return True, files

    def _prepare_overwrite_plan(self, root, families_present):
        plan = {}
        plan['lineup'] = self._prompt_family_overwrite('Lineup', os.path.join(root, DIR_EXPORT_LINEUP).replace('\\', '/'))
        if families_present.get('grey'):
            plan['grey'] = self._prompt_family_overwrite('Grey', os.path.join(root, DIR_EXPORT_GREY).replace('\\', '/'))
        if families_present.get('chart'):
            plan['chart'] = self._prompt_family_overwrite('Chart', os.path.join(root, DIR_EXPORT_CHART).replace('\\', '/'))
        if families_present.get('chrome'):
            plan['chrome'] = self._prompt_family_overwrite('Chrome', os.path.join(root, DIR_EXPORT_CHROME).replace('\\', '/'))
        if families_present.get('stmaps'):
            plan['stmaps'] = self._prompt_family_overwrite('ST Maps', os.path.join(root, DIR_EXPORT_STMAPS).replace('\\', '/'))
        return plan

    def _prompt_reprocess_raw_outputs(self, exp_dirs):
        counts = []
        total = 0
        for label, d in exp_dirs.items():
            try:
                cnt = len([f for f in os.listdir(d) if os.path.isfile(os.path.join(d, f))])
            except Exception:
                cnt = 0
            counts.append((label, cnt))
            total += cnt
        if total == 0:
            return 'append'
        lines = [f'{label}: {cnt}' for label, cnt in counts]
        msg = (
            'Existing outputs detected:\n' + '\n'.join(lines) + '\n\n'
            'Choose action:\n'
            'Wipe = delete all existing outputs in these folders\n'
            'Overwrite = keep folders, overwrite matching frames\n'
            'Append = keep existing files, skip already written frames\n'
            'Cancel = abort processing'
        )
        dlg = QMessageBox(self)
        dlg.setWindowTitle('Existing RAW outputs')
        dlg.setIcon(QMessageBox.Question)
        dlg.setText(msg)
        btn_wipe = dlg.addButton('Wipe', QMessageBox.ActionRole)
        btn_over = dlg.addButton('Overwrite', QMessageBox.YesRole)
        btn_append = dlg.addButton('Append', QMessageBox.NoRole)
        btn_cancel = dlg.addButton('Cancel', QMessageBox.RejectRole)
        self._with_temp_no_ontop(dlg.exec_)
        clicked = dlg.clickedButton()
        if clicked == btn_wipe:
            return 'wipe'
        if clicked == btn_over:
            return 'overwrite'
        if clicked == btn_append:
            return 'append'
        return 'cancel'

    def _prompt_family_overwrite(self, label, exp_dir):
        ensure_dir(exp_dir)
        existing = [f for f in os.listdir(exp_dir) if os.path.isfile(os.path.join(exp_dir, f))]
        if not existing:
            return 'overwrite'
        msg = (
            f'{label} export folder has {len(existing)} existing files:\n{exp_dir}\n\n'
            'Choose action:\n- Overwrite (replace matching frames)\n'
            '- Skip (leave existing files, do not reprocess)\n'
            '- Wipe Folder (delete ALL files in this folder before processing)'
        )
        action = self._with_temp_no_ontop(lambda: show_overwrite_dialog(self, f'{label} Existing Files', msg, include_wipe=True))
        if action == 'wipe':
            removed = remove_all_files_in_folder(exp_dir)
            self.log_msg(f'Wipe Folder: removed {removed} files from {exp_dir}')
            return 'overwrite'
        return action

    def scan_matches(self):
        man_path = self._active_manifest_path(allow_dialog=True)
        root = self.current_root()
        src_st = self.line_src_st.text().strip()
        src_raw = self.line_src_raw.text().strip()
        if not man_path or not os.path.exists(man_path):
            self._with_temp_no_ontop(lambda: QMessageBox.warning(self, 'Manifest', 'Choose a valid manifest JSON.'))
            return
        if not root:
            root = os.path.dirname(man_path)
        data = self._read_manifest(man_path)
        if not data:
            return
        entries = sorted(data.get('entries', []), key=lambda e: int(e.get('order_index', 0)))
        start_frame = int(self.spin_start.value() or DEFAULT_START_FRAME)
        st_files = self._scan_folder_for(src_st, EXR_EXTS)
        raw_files = self._scan_folder_for(src_raw, RAW_EXTS)
        ensure_dir(root)
        for d in [
            DIR_STMAPS, DIR_RAW, DIR_GREY, DIR_CHART, DIR_CHROME,
            DIR_EXPORT_LINEUP, DIR_EXPORT_GREY, DIR_EXPORT_CHART,
            DIR_EXPORT_CHROME, DIR_EXPORT_STMAPS
        ]:
            ensure_dir(os.path.join(root, d).replace('\\', '/'))
        self.table_matches.setRowCount(len(entries))
        missing_any = False
        for i, e in enumerate(entries):
            idx = int(e.get('order_index', 0))
            frame = start_frame + idx
            basename = (e.get('image_plane') or {}).get('basename') or ''
            stem = basename.lower()
            st_src = _match_stem_glob(stem, st_files)
            raw_src = _match_stem_glob(stem, raw_files)
            status = []
            if not st_src:
                status.append('NO ST')
            if not raw_src:
                status.append('NO RAW')
            status_str = 'OK' if not status else ', '.join(status)
            if status:
                missing_any = True
            self.table_matches.setItem(i, 0, QTableWidgetItem(str(idx)))
            self.table_matches.setItem(i, 1, QTableWidgetItem(str(frame)))
            self.table_matches.setItem(i, 2, QTableWidgetItem(basename))
            self.table_matches.setItem(i, 3, QTableWidgetItem(st_src))
            self.table_matches.setItem(i, 4, QTableWidgetItem(raw_src))
            it = QTableWidgetItem(status_str)
            color = QtGui.QColor(70, 150, 70) if status_str == 'OK' else QtGui.QColor(180, 70, 70)
            it.setForeground(QtGui.QBrush(color))
            self.table_matches.setItem(i, 5, it)
        if missing_any:
            self.log_msg('Scan: Some entries are missing ST or RAW (see Status). Only matched entries will be processed.')
        else:
            self.log_msg('Scan: All entries matched ST and RAW.')

    def _get_image_size_oiiotool(self, oiiotool, image_path):
        try:
            proc = run_silent(
                [oiiotool, image_path, '--info', '-v'],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            txt = proc.stdout or ''
            m = re.search(r'Resolution:\s*(\d+)\s*x\s*(\d+)', txt)
            if not m:
                m = re.search(r'(\d+)\s*x\s*(\d+)', txt)
            if m:
                return int(m.group(1)), int(m.group(2))
        except Exception as e:
            self.log_msg(f'Failed to query size for {image_path}: {e}')
        return None, None

    def _prepare_stmap_for_warp(self, oiiotool, st_path, target_w, target_h):
        """
        Returns (prepared_stmap_path, chan_s, chan_t).
        - Respects ST mode + custom fields.
        - Reorders channels when using name-based selection.
        - Resizes to match RAW resolution.
        """
        if not st_path or not os.path.exists(st_path):
            return None, 0, 1

        mode = self.combo_st_mode.currentText()
        custom = self.line_st_custom.text().strip()

        chan_s = 0
        chan_t = 1
        name_s = None
        name_t = None
        use_names = False

        if mode.startswith('RGB'):
            chan_s, chan_t = 0, 1
        elif mode.startswith('UV'):
            name_s, name_t = 'u', 'v'
            use_names = True
        else:  # Custom
            if custom:
                parts = [p.strip() for p in custom.replace('/', ',').split(',') if p.strip()]
                if len(parts) >= 2:
                    if parts[0].isdigit() and parts[1].isdigit():
                        chan_s, chan_t = int(parts[0]), int(parts[1])
                    else:
                        name_s, name_t = parts[0], parts[1]
                        use_names = True

        st_cur = st_path

        # If using named channels, first collapse to those via --ch
        if use_names and name_s and name_t:
            base, ext = os.path.splitext(os.path.basename(st_path))
            st_named = os.path.join(
                os.path.dirname(st_path),
                f'{base}_{name_s}{name_t}{ext}'
            ).replace('\\', '/')
            if not os.path.exists(st_named):
                cmd = [oiiotool, st_cur, '--ch', f'{name_s},{name_t}', '-o', st_named]
                self.log_msg(f'oiiotool (select ST channels): {" ".join(cmd)}')
                try:
                    proc = run_silent(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                    if proc.returncode != 0:
                        self.log_msg(f'oiiotool --ch failed for {st_path}:\n{proc.stderr}')
                    else:
                        self.log_msg(f'ST map channels -> {st_named}')
                        st_cur = st_named
                        chan_s, chan_t = 0, 1
                except Exception as e:
                    self.log_msg(f'Error running oiiotool --ch: {e}')

        # Resize ST map to match RAW resolution
        if target_w and target_h:
            base, ext = os.path.splitext(os.path.basename(st_cur))
            st_resized = os.path.join(
                os.path.dirname(st_cur),
                f'{base}_resized_{target_w}x{target_h}{ext}'
            ).replace('\\', '/')
            if not os.path.exists(st_resized):
                cmd = [oiiotool, st_cur, '--resize', f'{target_w}x{target_h}', '-o', st_resized]
                self.log_msg(f'oiiotool (resize ST): {" ".join(cmd)}')
                try:
                    proc = run_silent(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                    if proc.returncode != 0:
                        self.log_msg(f'oiiotool resize failed for {st_cur} -> {st_resized}:\n{proc.stderr}')
                    else:
                        self.log_msg(f'Resized ST map -> {st_resized}')
                        st_cur = st_resized
                except Exception as e:
                    self.log_msg(f'Error running oiiotool resize: {e}')
            else:
                st_cur = st_resized

        return st_cur, chan_s, chan_t

    def _run_oiiotool_raw_to_acescg(self, oiiotool, raw_path, out_exr_path, highlight_mode='0', debug=False):
        cmd = [
            oiiotool,
            '-iconfig', 'raw:ColorSpace', 'ACES',
            '-iconfig', 'raw:HighlightMode', str(highlight_mode),
            '-iconfig', 'raw:use_camera_wb', '1',
            '-i', raw_path
        ]
        if debug:
            cmd.append('--debug')
        cmd += [
            '--colorconvert', 'ACES - ACES2065-1', 'ACES - ACEScg',
            '--compression', 'zips',
            '-d', 'half',
            '-o', out_exr_path
        ]
        try:
            self.log_msg(f'oiiotool RAW->ACEScg: {" ".join(cmd)}')
            proc = run_silent(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            return proc.returncode, proc.stdout, proc.stderr
        except Exception as e:
            return 1, '', f'Failed to run oiiotool: {e}'

    def _run_oiiotool_stwarp(self, oiiotool, input_exr, stmap_exr, output_exr,
                             chan_s=0, chan_t=1, debug=False):
        """
        Uses oiiotool --st_warp to undistort with ST map.
        We assume stmap has been resized to match input_exr.
        """
        cmd = [oiiotool]
        if debug:
            cmd.append('--debug')
        cmd += [
            input_exr,
            stmap_exr,
            f'--st_warp:chan_s={chan_s}:chan_t={chan_t}:flip_t=1',
            '--compression', 'zips',
            '-d', 'half',
            '-o', output_exr
        ]
        self.log_msg(f'oiiotool ST-warp: {" ".join(cmd)}')
        try:
            proc = run_silent(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            if proc.returncode != 0:
                return False, proc.stderr
            return True, None
        except Exception as e:
            return False, f'Failed to run oiiotool st_warp: {e}'

    def scan_matches(self):
        man_path = self._active_manifest_path(allow_dialog=True)
        root = self.current_root()
        src_st = self.line_src_st.text().strip()
        src_raw = self.line_src_raw.text().strip()
        if not man_path or not os.path.exists(man_path):
            QMessageBox.warning(self, 'Manifest', 'Choose a valid manifest JSON.')
            return
        if not root:
            root = os.path.dirname(man_path)
        data = self._read_manifest(man_path)
        if not data:
            return
        entries = sorted(
            data.get('entries', []),
            key=lambda e: int(e.get('order_index', 0))
        )
        start_frame = int(self.spin_start.value() or DEFAULT_START_FRAME)

        # Map stems in source folders (file lists only; real mapping is via glob per stem)
        st_files = self._scan_folder_for(src_st, EXR_EXTS)
        raw_files = self._scan_folder_for(src_raw, RAW_EXTS)

        # Prepare root subdirs
        ensure_dir(root)
        for d in [
            DIR_STMAPS, DIR_RAW, DIR_GREY, DIR_CHART, DIR_CHROME,
            DIR_EXPORT_LINEUP, DIR_EXPORT_GREY, DIR_EXPORT_CHART, DIR_EXPORT_CHROME
        ]:
            ensure_dir(os.path.join(root, d).replace('\\', '/'))

        # Fill table
        self.table_matches.setRowCount(len(entries))
        missing_any = False
        for i, e in enumerate(entries):
            idx = int(e.get('order_index', 0))
            frame = start_frame + idx
            basename = (e.get('image_plane') or {}).get('basename') or ''
            stem = basename.lower()

            st_src = _match_stem_glob(stem, st_files)
            raw_src = _match_stem_glob(stem, raw_files)

            status = []
            if not st_src:
                status.append('NO ST')
            if not raw_src:
                status.append('NO RAW')
            status_str = 'OK' if not status else ', '.join(status)
            if status:
                missing_any = True

            self.table_matches.setItem(i, 0, QTableWidgetItem(str(idx)))
            self.table_matches.setItem(i, 1, QTableWidgetItem(str(frame)))
            self.table_matches.setItem(i, 2, QTableWidgetItem(basename))
            self.table_matches.setItem(i, 3, QTableWidgetItem(st_src))
            self.table_matches.setItem(i, 4, QTableWidgetItem(raw_src))
            it = QTableWidgetItem(status_str)
            color = QtGui.QColor(70, 150, 70) if status_str == 'OK' else QtGui.QColor(180, 70, 70)
            it.setForeground(QtGui.QBrush(color))
            self.table_matches.setItem(i, 5, it)

        if missing_any:
            self.log_msg(
                'Scan: Some entries are missing ST or RAW (see Status column). '
                'Only matched entries will be processed.'
            )
        else:
            self.log_msg('Scan: All entries matched ST and RAW.')

    def undistort_process(self):
        man_path = self._active_manifest_path(allow_dialog=True)
        if not man_path or not os.path.exists(man_path):
            QMessageBox.warning(self, 'Manifest', 'Choose a valid manifest JSON.')
            return

        root = self.current_root() or os.path.dirname(man_path)

        # Ensure subfolders
        for d in [
            DIR_STMAPS, DIR_RAW, DIR_GREY, DIR_CHART, DIR_CHROME,
            DIR_EXPORT_LINEUP, DIR_EXPORT_GREY, DIR_EXPORT_CHART, DIR_EXPORT_CHROME
        ]:
            ensure_dir(os.path.join(root, d).replace('\\', '/'))

        oiiotool = self.line_oiio.text().strip() or DEFAULT_OIIOTOOL
        if not os.path.exists(oiiotool):
            QMessageBox.critical(self, 'oiiotool', f'oiiotool not found at:\n{oiiotool}')
            return

        src_st = self.line_src_st.text().strip()
        src_raw = self.line_src_raw.text().strip()
        src_grey = self.line_src_grey.text().strip()
        src_chart = self.line_src_chart.text().strip()
        src_chrome = self.line_src_chrome.text().strip()

        data = self._read_manifest(man_path)
        if not data:
            return
        lineup_block = data.get('lineup', {}) or {}
        start_frame = int(lineup_block.get('start_frame', self.spin_start.value() or DEFAULT_START_FRAME))
        end_frame = int(lineup_block.get('end_frame', start_frame + max(0, len(data.get('entries', [])) - 1)))
        debug_oiio = self.chk_und_debug.isChecked()
        highlight_mode = '0' if self.combo_highlight_mode.currentIndex() == 0 else '2'
        entries = sorted(
            data.get('entries', []),
            key=lambda e: int(e.get('order_index', 0))
        )
        if not entries:
            self.log_msg('Manifest has no entries.')
            return

        # Build file lists for each family
        st_files = self._scan_folder_for(src_st, EXR_EXTS)
        raw_files = self._scan_folder_for(src_raw, RAW_EXTS)
        grey_files = self._scan_folder_for(src_grey, RAW_EXTS) if src_grey else []
        chart_files = self._scan_folder_for(src_chart, RAW_EXTS) if src_chart else []
        chrome_files = self._scan_folder_for(src_chrome, RAW_EXTS) if src_chrome else []

        if src_grey and not grey_files:
            self.log_msg(f'GREY RAW folder has no supported files: {src_grey}')
        if src_chart and not chart_files:
            self.log_msg(f'CHART RAW folder has no supported files: {src_chart}')
        if src_chrome and not chrome_files:
            self.log_msg(f'CHROME RAW folder has no supported files: {src_chrome}')

        # Copy matched files into project root subfolders, renaming ST maps as sequence
        st_dst_dir = os.path.join(root, DIR_STMAPS).replace('\\', '/')
        raw_dst_dir = os.path.join(root, DIR_RAW).replace('\\', '/')
        grey_dst_dir = os.path.join(root, DIR_GREY).replace('\\', '/')
        chart_dst_dir = os.path.join(root, DIR_CHART).replace('\\', '/')
        chrome_dst_dir = os.path.join(root, DIR_CHROME).replace('\\', '/')

        total = len(entries)
        self.log_msg(f'Undistort: {total} manifest entries.')

        # Progress dialog to keep UI responsive and avoid focus-stealing consoles
        progress = QProgressDialog('Processing RAW...', 'Cancel', 0, total, self)
        progress.setWindowTitle('RAW Processing')
        progress.setWindowModality(QtCore.Qt.WindowModal)
        progress.setMinimumDuration(0)
        progress.show()
        QtWidgets.QApplication.processEvents()

        # First pass: copy all sources into their root subfolders with sequence names
        st_seq_map = {}   # frame -> stmap path in st_dst_dir
        raw_seq_map = {}  # frame -> raw path in raw_dst_dir
        grey_seq_map = {}
        chart_seq_map = {}
        chrome_seq_map = {}

        canceled = False

        for e in entries:
            idx = int(e.get('order_index', 0))
            frame = start_frame + idx
            basename = (e.get('image_plane') or {}).get('basename') or ''
            stem = basename.lower()

            st_src = _match_stem_glob(stem, st_files)
            raw_src = _match_stem_glob(stem, raw_files)
            grey_src = _match_stem_glob(stem, grey_files) if grey_files else ''
            chart_src = _match_stem_glob(stem, chart_files) if chart_files else ''
            chrome_src = _match_stem_glob(stem, chrome_files) if chrome_files else ''

            # ST map -> stmaps/stmap.%04d.ext
            if st_src:
                ext = os.path.splitext(st_src)[1]
                dst = os.path.join(st_dst_dir, f'stmap.{frame:04d}{ext}').replace('\\', '/')
                try:
                    if not os.path.exists(dst):
                        shutil.copy2(st_src, dst)
                    st_seq_map[frame] = dst
                except Exception as ce:
                    self.log_msg(f'Failed to copy ST map {st_src} -> {dst}: {ce}')
            else:
                self.log_msg(f'Warning: No ST map for stem "{basename}" (frame {frame})')

            # Main RAW -> raw/... (copy both original RAW and converted EXR with same filename)
            if raw_src:
                dst = os.path.join(
                    raw_dst_dir,
                    os.path.basename(raw_src)
                ).replace('\\', '/')
                try:
                    if not os.path.exists(dst):
                        shutil.copy2(raw_src, dst)
                    raw_seq_map[frame] = dst
                except Exception as ce:
                    self.log_msg(f'Failed to copy RAW {raw_src} -> {dst}: {ce}')
            else:
                self.log_msg(f'Warning: No RAW for stem "{basename}" (frame {frame})')

            # Grey RAW
            if grey_src:
                dst = os.path.join(
                    grey_dst_dir,
                    os.path.basename(grey_src)
                ).replace('\\', '/')
                try:
                    if not os.path.exists(dst):
                        shutil.copy2(grey_src, dst)
                    grey_seq_map[frame] = dst
                except Exception as ce:
                    self.log_msg(f'Failed to copy GREY {grey_src} -> {dst}: {ce}')

            # Chart RAW
            if chart_src:
                dst = os.path.join(
                    chart_dst_dir,
                    os.path.basename(chart_src)
                ).replace('\\', '/')
                try:
                    if not os.path.exists(dst):
                        shutil.copy2(chart_src, dst)
                    chart_seq_map[frame] = dst
                except Exception as ce:
                    self.log_msg(f'Failed to copy CHART {chart_src} -> {dst}: {ce}')

            # Chrome RAW
            if chrome_src:
                dst = os.path.join(
                    chrome_dst_dir,
                    os.path.basename(chrome_src)
                ).replace('\\', '/')
                try:
                    if not os.path.exists(dst):
                        shutil.copy2(chrome_src, dst)
                    chrome_seq_map[frame] = dst
                except Exception as ce:
                    self.log_msg(f'Failed to copy CHROME {chrome_src} -> {dst}: {ce}')

        # Export directories – each family has its own export folder
        exp_lineup_dir = os.path.join(root, DIR_EXPORT_LINEUP).replace('\\', '/')
        exp_grey_dir = os.path.join(root, DIR_EXPORT_GREY).replace('\\', '/')
        exp_chart_dir = os.path.join(root, DIR_EXPORT_CHART).replace('\\', '/')
        exp_chrome_dir = os.path.join(root, DIR_EXPORT_CHROME).replace('\\', '/')

        # Decide reprocess policy for existing outputs
        choice = self._prompt_reprocess_raw_outputs({
            'Lineup': exp_lineup_dir,
            'Grey': exp_grey_dir,
            'Chart': exp_chart_dir,
            'Chrome': exp_chrome_dir
        })
        if choice == 'cancel':
            self.log_msg('Undistort canceled by user.')
            return
        overwrite = choice in ('overwrite', 'wipe')
        if choice == 'wipe':
            for d in [exp_lineup_dir, exp_grey_dir, exp_chart_dir, exp_chrome_dir]:
                removed = remove_all_files_in_folder(d)
                if removed:
                    self.log_msg(f'Wipe: removed {removed} files from {d}')

        done = 0
        num_entries = len(entries)

        for e in entries:
            idx = int(e.get('order_index', 0))
            frame = start_frame + idx
            basename = (e.get('image_plane') or {}).get('basename') or ''

            if progress.wasCanceled():
                canceled = True
                self.log_msg('RAW processing canceled by user.')
                break

            # Main camera RAW processing
            raw_path = raw_seq_map.get(frame)
            st_path = st_seq_map.get(frame)

            out_raw = os.path.join(
                exp_lineup_dir,
                f'lineup_raw.{frame:04d}.exr'
            ).replace('\\', '/')
            out_und = os.path.join(
                exp_lineup_dir,
                f'lineup_raw_undistorted.{frame:04d}.exr'
            ).replace('\\', '/')
            raw_copy_exr = os.path.join(raw_dst_dir, os.path.splitext(os.path.basename(raw_path or ''))[0] + '.exr').replace('\\', '/')

            if not raw_path:
                self.log_msg(f'MISSING RAW for stem "{basename}" (frame {frame})')
            else:
                # RAW -> ACEScg EXR
                if os.path.exists(raw_copy_exr) and not overwrite:
                    # Already converted once; reuse without reprocessing
                    try:
                        shutil.copy2(raw_copy_exr, out_raw)
                        self.log_msg(f'Using cached RAW EXR: {raw_copy_exr} -> {out_raw}')
                    except Exception as ce:
                        self.log_msg(f'Failed to copy cached EXR {raw_copy_exr}: {ce}')
                if not os.path.exists(out_raw):
                    rc, out, err = self._run_oiiotool_raw_to_acescg(
                        oiiotool, raw_path, out_raw, highlight_mode=highlight_mode, debug=debug_oiio
                    )
                    if rc != 0 or not os.path.exists(out_raw):
                        self.log_msg(
                            f'RAW->ACEScg failed for {raw_path}\nReturn={rc}\n{err}'
                        )
                    else:
                        self.log_msg(f'RAW->ACEScg: {raw_path} -> {out_raw}')
                else:
                    self.log_msg(f'Using existing: {out_raw}')

                # Ensure copy in raw folder with same basename
                if os.path.exists(out_raw):
                    try:
                        if overwrite or not os.path.exists(raw_copy_exr):
                            shutil.copy2(out_raw, raw_copy_exr)
                            self.log_msg(f'Cached RAW EXR written: {raw_copy_exr}')
                    except Exception as ce:
                        self.log_msg(f'Failed to copy EXR to raw folder: {ce}')

            # Undistort via ST map (if available)
            if os.path.exists(out_raw):
                if st_path:
                    w, h = self._get_image_size_oiiotool(oiiotool, out_raw)
                    st_prepared, chan_s, chan_t = self._prepare_stmap_for_warp(
                        oiiotool, st_path, w, h
                    )
                    if st_prepared and os.path.exists(st_prepared):
                        ok, err = self._run_oiiotool_stwarp(
                            oiiotool, out_raw, st_prepared,
                            out_und, chan_s=chan_s, chan_t=chan_t,
                            debug=debug_oiio
                        )
                        if not ok:
                            self.log_msg(
                                f'Undistort failed for "{basename}" '
                                f'(frame {frame}): {err}'
                            )
                            try:
                                shutil.copy2(out_raw, out_und)
                                self.log_msg(
                                    f'Fallback copied RAW to undistorted: {out_und}'
                                )
                            except Exception as ce:
                                self.log_msg(f'Failed fallback copy: {ce}')
                        else:
                            self.log_msg(f'Undistorted -> {out_und}')
                    else:
                        self.log_msg(
                            f'ST map prep failed for frame {frame}; '
                            f'copying RAW to undistorted.'
                        )
                        try:
                            shutil.copy2(out_raw, out_und)
                        except Exception as ce:
                            self.log_msg(f'Failed to copy output: {ce}')
                else:
                    self.log_msg(
                        f'No ST map for "{basename}" (frame {frame}). '
                        f'Copying RAW exr to undistorted.'
                    )
                    try:
                        shutil.copy2(out_raw, out_und)
                        self.log_msg(f'Wrote: {out_und}')
                    except Exception as ce:
                        self.log_msg(f'Failed to copy output: {ce}')

            # Grey / Chart / Chrome families
            def process_family(label, family_map, exp_dir, base_stub, expected_src_dir=None):
                src = family_map.get(frame)
                if not src:
                    return

                if expected_src_dir:
                    expected_root = os.path.abspath(expected_src_dir)
                    src_root = os.path.abspath(os.path.dirname(src))
                    if not src_root.startswith(expected_root):
                        self.log_msg(
                            f'{label} source not in its RAW folder; skipping to avoid using lineup RAW. '
                            f'Source: {src}'
                        )
                        return
                out_raw_f = os.path.join(
                    exp_dir,
                    f'{base_stub}.{frame:04d}.exr'
                ).replace('\\', '/')
                out_und_f = os.path.join(
                    exp_dir,
                    f'{base_stub}_undistorted.{frame:04d}.exr'
                ).replace('\\', '/')

                if os.path.exists(out_raw_f) and os.path.exists(out_und_f) and not overwrite:
                    self.log_msg(f'SKIP (exists): {label} frame {frame}')
                    return

                # RAW -> ACEScg (no shared cache reuse for auxiliary families)
                if not os.path.exists(out_raw_f):
                    rc, out, err = self._run_oiiotool_raw_to_acescg(
                        oiiotool, src, out_raw_f, highlight_mode=highlight_mode, debug=debug_oiio
                    )
                    if rc != 0 or not os.path.exists(out_raw_f):
                        self.log_msg(
                            f'{label} RAW->ACEScg failed for {src}\nReturn={rc}\n{err}'
                        )
                        return
                    else:
                        self.log_msg(f'{label} RAW->ACEScg: {src} -> {out_raw_f}')
                else:
                    self.log_msg(f'Using existing {label}: {out_raw_f}')

                # Use same ST map as main (if present)
                if st_path and os.path.exists(out_raw_f):
                    w_f, h_f = self._get_image_size_oiiotool(oiiotool, out_raw_f)
                    st_prepared_f, chan_s_f, chan_t_f = self._prepare_stmap_for_warp(
                        oiiotool, st_path, w_f, h_f
                    )
                    if st_prepared_f and os.path.exists(st_prepared_f):
                        ok, err = self._run_oiiotool_stwarp(
                            oiiotool, out_raw_f, st_prepared_f,
                            out_und_f, chan_s=chan_s_f, chan_t=chan_t_f,
                            debug=debug_oiio
                        )
                        if not ok:
                            self.log_msg(
                                f'{label} undistort failed (frame {frame}): {err}'
                            )
                            try:
                                shutil.copy2(out_raw_f, out_und_f)
                                self.log_msg(
                                    f'{label} fallback copied RAW to undistorted: '
                                    f'{out_und_f}'
                                )
                            except Exception as ce:
                                self.log_msg(f'{label} failed fallback copy: {ce}')
                        else:
                            self.log_msg(f'{label} undistorted -> {out_und_f}')
                    else:
                        self.log_msg(
                            f'{label}: ST map prep failed, copying RAW to undistorted.'
                        )
                        try:
                            shutil.copy2(out_raw_f, out_und_f)
                            self.log_msg(f'{label} wrote: {out_und_f}')
                        except Exception as ce:
                            self.log_msg(f'{label} failed to copy output: {ce}')
                else:
                    if not st_path:
                        self.log_msg(
                            f'{label}: No ST map; copying RAW exr to undistorted.'
                        )
                    try:
                        shutil.copy2(out_raw_f, out_und_f)
                        self.log_msg(f'{label} wrote: {out_und_f}')
                    except Exception as ce:
                        self.log_msg(f'{label} failed to copy output: {ce}')

            # Process optional families
            if grey_seq_map:
                process_family('GREY', grey_seq_map, exp_grey_dir, 'grey', expected_src_dir=grey_dst_dir)
            if chart_seq_map:
                process_family('CHART', chart_seq_map, exp_chart_dir, 'chart', expected_src_dir=chart_dst_dir)
            if chrome_seq_map:
                process_family('CHROME', chrome_seq_map, exp_chrome_dir, 'chrome', expected_src_dir=chrome_dst_dir)

            done += 1
            if done % 5 == 0 or done == num_entries:
                self.log_msg(f'Progress: {done}/{num_entries} entries processed.')
            progress.setValue(done)
            QtWidgets.QApplication.processEvents()

        progress.close()
        # Restore window
        self.showNormal()
        self.raise_()
        self.activateWindow()

        if canceled:
            QMessageBox.information(self, 'Undistort', f'Processing canceled. {done}/{total} entries handled.')
        else:
            QMessageBox.information(self, 'Undistort', f'Processing finished. {done}/{total} entries handled.')

        # Refresh Nuke script now that outputs exist (optional families pruned if empty)
        try:
            manifest = self._read_manifest(man_path) or {}
            lineup_block = manifest.get('lineup') or {}
            lineup_block['start_frame'] = start_frame
            lineup_block['end_frame'] = end_frame
            manifest['lineup'] = lineup_block
            self._write_nuke_script(root, manifest, strip_optional=True)
        except Exception as e:
            self.log_msg(f'Failed to update Nuke script after RAW process: {e}')



    # ------------- Load UI from manifest -------------
    def load_ui_from_manifest(self):
        path = self._active_manifest_path()
        if not path or not os.path.exists(path):
            path, _ = QFileDialog.getOpenFileName(self, 'Choose manifest JSON', '', 'JSON (*.json)')
            if not path:
                return
            self.line_custom_manifest.setText(path.replace('\\', '/'))
            self.chk_custom_manifest.setChecked(True)
        data = self._read_manifest(path)
        if not data:
            QMessageBox.warning(self, 'Manifest', 'Failed to read manifest JSON.')
            return
        ui_state = data.get('ui_state') or {}
        if not ui_state:
            QMessageBox.warning(self, 'Manifest', 'Manifest has no ui_state block to recall.')
            return
        proj = ui_state.get('project', '')
        asset = ui_state.get('asset', '')
        custom_root_enabled = ui_state.get('custom_root_enabled', False)
        custom_root_path = ui_state.get('custom_root_path', '')
        base_name = ui_state.get('base_name', 'imageplane')
        manifest_name = ui_state.get('manifest_name', '')
        start_frame = int(ui_state.get('start_frame', DEFAULT_START_FRAME))
        create_alt = ui_state.get('create_alt', False)
        alt_aspect = float(ui_state.get('alt_aspect', 1.667))
        camera_list = ui_state.get('camera_list', [])
        if proj:
            idx = self.combo_project.findText(proj)
            if idx >= 0:
                self.combo_project.setCurrentIndex(idx)
            else:
                self.log_msg(f'Project "{proj}" not in current project list; leaving as-is.')
        if asset:
            idx_a = self.combo_asset.findText(asset)
            if idx_a >= 0:
                self.combo_asset.setCurrentIndex(idx_a)
            else:
                self.combo_asset.setEditText(asset)
        self.chk_custom_root.setChecked(bool(custom_root_enabled))
        self.line_custom_root.setText(custom_root_path)
        if not custom_root_enabled:
            self._update_computed_root()
        self.line_basename.setText(base_name)
        # manifest name is auto-computed; custom paths live in the custom manifest field
        self.spin_start.setValue(start_frame)
        self.chk_overwrite_imageplanes.setChecked(bool(ui_state.get('overwrite_imageplanes', True)))
        self.chk_copy_all_imageplanes.setChecked(bool(ui_state.get('copy_all_imageplanes', True)))
        self.chk_import_charts.setChecked(bool(ui_state.get('import_charts', True)))
        self.chk_animate_lights.setChecked(bool(ui_state.get('animate_lights', False)))
        self.chk_matchmove_cam.setChecked(bool(ui_state.get('matchmove_cam', True)))
        self.chk_clearangle_mode.setChecked(bool(ui_state.get('clearangle_mode', False)))
        ca_preset = ui_state.get('clearangle_preset', self.combo_ca_preset.currentText())
        idx = self.combo_ca_preset.findText(ca_preset)
        if idx >= 0:
            self.combo_ca_preset.setCurrentIndex(idx)
        self.chk_create_alt_cam.setChecked(bool(create_alt))
        self.spin_alt_aspect.setValue(float(alt_aspect))
        self.listCams.clear()
        for cam in camera_list:
            self.listCams.addItem(QListWidgetItem(cam))
        lineup = data.get('lineup', {}) or {}
        l_start = int(lineup.get('start_frame', start_frame))
        self.spin_und_start.setValue(l_start)
        # Root is derived from pipeline/custom root settings
        QMessageBox.information(self, 'Manifest', 'UI state and camera list recalled from manifest.\nAdjust asset/root as needed, then rebuild or process.')

# ----------------------------- Launch (single instance) -----------------------------
try:
    _lineup_ui.close()
except Exception:
    pass

_lineup_ui = LineupCamTool()
_lineup_ui.show()