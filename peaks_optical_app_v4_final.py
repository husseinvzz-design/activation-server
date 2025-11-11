# peaks_optical_app_v3.py
# Merged features: vision tests, inventory management, invoices (PDF+QR), birthdays reminders, image uploads
# Requires: PySide6; optional: reportlab, qrcode, Pillow
# Run:
#   pip install PySide6
#   pip install reportlab qrcode[pil] Pillow   # optional for PDF/QR/image features
#   python peaks_optical_app_v3.py

import sys, os, sqlite3, shutil, webbrowser, csv, configparser, io
from datetime import datetime, timedelta
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QPropertyAnimation, QEasingCurve, QRect, QDate
from PySide6.QtGui import QFont, QPixmap, QImage
from PySide6.QtWidgets import (
    QApplication, QWidget, QMainWindow, QLabel, QLineEdit, QPushButton,
    QVBoxLayout, QHBoxLayout, QStackedWidget, QListWidget, QListWidgetItem,
    QMessageBox, QTableWidget, QTableWidgetItem, QHeaderView, QComboBox,
    QSpinBox, QTextEdit, QFileDialog, QFormLayout, QFrame, QDialog, QInputDialog,
    QGraphicsDropShadowEffect, QDateEdit, QDialogButtonBox, QGridLayout, QGroupBox
)

# optional charts (PySide6.QtCharts)
try:
    from PySide6.QtCharts import QChart, QChartView, QBarSeries, QBarSet, QBarCategoryAxis
    CHARTS_AVAILABLE = True
except Exception:
    CHARTS_AVAILABLE = False

# optional PDF and QR generation
try:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas as rl_canvas
    from reportlab.lib.units import mm
    REPORTLAB_AVAILABLE = True
except Exception:
    REPORTLAB_AVAILABLE = False

try:
    import qrcode
    QRCODE_AVAILABLE = True
except Exception:
    QRCODE_AVAILABLE = False

try:
    from PIL import Image
    PIL_AVAILABLE = True
except Exception:
    PIL_AVAILABLE = False

# ---------------- App settings ----------------
APP_NAME = "Peaks Optical"
DB_FILE = "peaks_optical.db"
CONFIG_FILE = "peaks_settings.ini"
LOGO_FILE = "logo.png"

# directories for images & invoices
IMAGES_DIR = Path('images')
IMAGES_CUSTOMERS = IMAGES_DIR / 'customers'
IMAGES_INVENTORY = IMAGES_DIR / 'inventory'
INVOICES_DIR = Path('invoices')
for d in [IMAGES_CUSTOMERS, IMAGES_INVENTORY, INVOICES_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# UI size variables
TOP_BAR_HEIGHT = 70
TOP_BUTTON_WIDTH = 150
TOP_BUTTON_HEIGHT = 40

# Ensure config exists
cfg = configparser.ConfigParser()
if not Path(CONFIG_FILE).exists():
    cfg['DEFAULT'] = {'language': 'ar', 'remember_user': 'no', 'remembered_username': ''}
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        cfg.write(f)
else:
    cfg.read(CONFIG_FILE, encoding='utf-8')

# clinic name from settings (can be empty). Use CLINIC_NAME or fallback to APP_NAME
CLINIC_NAME = cfg['DEFAULT'].get('clinic_name', '')


# ---------------- Styles ----------------
PRIMARY_COLOR = "#4da6ff"
PRIMARY_HOVER = "#3399ff"
LIGHT_BTN_BG = "#e6f2ff"
LIGHT_BTN_HOVER = "#cce6ff"
TEXT_ON_LIGHT_BTN = "#004080"
TEXT_DEFAULT = "#0f172a"

APP_STYLE = f"""
* {{ font-family: 'Cairo', 'Segoe UI', sans-serif; }}
QWidget {{ background: qlineargradient(x1:0 y1:0, x2:0 y2:1, stop:0 #f8fbff, stop:1 #ffffff); color: {TEXT_DEFAULT}; }}
#topbar {{ background: qlineargradient(x1:0 y1:0, x2:1 y2:0, stop:0 #eef6ff, stop:1 #ffffff); border-bottom: 1px solid #e6eef8; padding: 6px; }}
#sidebar {{ background: #f6fbff; border-right: 1px solid #e6eef8; }}
QListWidget {{ background: transparent; border: none; }}
QListWidget::item {{ padding: 12px 10px; margin: 4px; border-radius: 8px; }}
QListWidget::item:selected {{ background: qlineargradient(x1:0 y1:0, x2:1 y2:0, stop:0 #dbeafe, stop:1 #93c5fd); color: #042a63; }}
QFrame.card {{ background: white; border-radius: 10px; padding: 12px; border:1px solid #e6eef8; }}
QTableWidget {{ background: white; gridline-color:#e6eef8; }}
QHeaderView::section {{ background: #1e40af; color: white; padding:6px; }}
QLineEdit, QTextEdit, QComboBox, QSpinBox, QDateEdit {{ background: white; border: 1px solid #e6eef8; border-radius:6px; padding:6px; color: {TEXT_DEFAULT}; }}

/* Primary button */
QPushButton[role="primary"] {{
    background: {PRIMARY_COLOR}; color: white; border-radius: 10px;
    padding: 8px 12px; font-weight:700;
}}
QPushButton[role="primary"]:hover {{
    background: {PRIMARY_HOVER};
}}

/* Light action buttons (add, settings, reports) */
QPushButton[role="light"] {{
    background: {LIGHT_BTN_BG}; color: {TEXT_ON_LIGHT_BTN}; border-radius: 10px;
    padding: 8px 12px; font-weight:700; border:1px solid rgba(0,0,0,0.03);
}}
QPushButton[role="light"]:hover {{
    background: {LIGHT_BTN_HOVER};
}}

/* Muted / neutral */
QPushButton[role="muted"] {{
    background: #f3f4f6; color: {TEXT_DEFAULT}; border-radius: 10px; padding: 8px 12px; font-weight:700;
}}
QPushButton[role="muted"]:hover {{ background: #eceff4; }}

/* Danger */
QPushButton[role="danger"] {{
    background: #ff6b6b; color: white; border-radius: 10px; padding: 8px 12px; font-weight:700;
}}
QPushButton[role="danger"]:hover {{ background: #ff3b3b; }}
"""

# ---------------- Database init & migrations ----------------
def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    # existing tables
    c.execute('''CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, username TEXT UNIQUE, password TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS customers (
                    id INTEGER PRIMARY KEY,
                    name TEXT,
                    age INTEGER,
                    lens_type TEXT,
                    date TEXT,
                    total REAL,
                    paid REAL,
                    remaining REAL,
                    phone TEXT,
                    notes TEXT,
                    birth_date TEXT,
                    image_path TEXT)''')  # added birth_date, image_path

    c.execute('''CREATE TABLE IF NOT EXISTS lenses (id INTEGER PRIMARY KEY, name TEXT UNIQUE, image_path TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS reminders (
                    id INTEGER PRIMARY KEY,
                    sale_id INTEGER,
                    remind_date TEXT,
                    type TEXT,
                    sent INTEGER DEFAULT 0,
                    status TEXT DEFAULT 'pending')''')

    # new: vision tests
    c.execute('''CREATE TABLE IF NOT EXISTS vision_tests (
                    id INTEGER PRIMARY KEY,
                    customer_id INTEGER,
                    date TEXT,
                    right_sph REAL, right_cyl REAL, right_axis REAL,
                    left_sph REAL, left_cyl REAL, left_axis REAL,
                    notes TEXT,
                    next_exam_date TEXT)''')

    # new: inventory
    c.execute('''CREATE TABLE IF NOT EXISTS inventory (
                    id INTEGER PRIMARY KEY,
                    type TEXT,     -- 'lens' or 'frame'
                    name TEXT,     -- product name
                    brand TEXT,
                    size TEXT,
                    quantity INTEGER,
                    price REAL,
                    image_path TEXT)''')

    # new: invoices metadata
    c.execute('''CREATE TABLE IF NOT EXISTS invoices (
                    id INTEGER PRIMARY KEY,
                    sale_id INTEGER,
                    invoice_no TEXT UNIQUE,
                    file_path TEXT,
                    date TEXT,
                    total REAL)''')

    conn.commit()
    # ensure at least one user
    c.execute('SELECT COUNT(*) FROM users')
    if c.fetchone()[0] == 0:
        c.execute('INSERT INTO users (username,password) VALUES (?,?)', ('admin','admin'))
        conn.commit()
    conn.close()

# ---------------- Helpers ----------------
def open_whatsapp(phone, message):
    if not phone:
        QMessageBox.warning(None, 'خطأ', 'لا يوجد رقم هاتف لإرسال الرسالة')
        return
    phone_digits = ''.join(ch for ch in phone if ch.isdigit())
    text = message.replace(' ', '%20')
    url = f"https://wa.me/{phone_digits}?text={text}"
    webbrowser.open(url)

def backup_db_quick():
    src = Path(DB_FILE)
    if not src.exists():
        return None
    backup_dir = Path('backups'); backup_dir.mkdir(exist_ok=True)
    dest = backup_dir / f"backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
    shutil.copy2(src, dest)
    files = sorted(backup_dir.glob("backup_*.db"), key=os.path.getmtime, reverse=True)
    for old in files[50:]:
        try: old.unlink()
        except: pass
    return str(dest)

def backup_db_saveas(parent):
    src = Path(DB_FILE)
    if not src.exists():
        QMessageBox.warning(parent, 'خطأ', 'ملف قاعدة البيانات غير موجود.'); return None
    dest, _ = QFileDialog.getSaveFileName(parent, 'حفظ النسخة الاحتياطية', f'backup_{datetime.now().strftime("%Y%m%d_%H%M%S")}.db', 'Database Files (*.db)')
    if dest:
        shutil.copy2(src, dest)
        return dest
    return None

def restore_db_from_file(parent):
    src, _ = QFileDialog.getOpenFileName(parent, 'اختر ملف النسخة الاحتياطية', '', 'Database Files (*.db)')
    if src:
        shutil.copy2(src, DB_FILE)
        return True
    return False

def save_image_file(source_path, dest_dir, prefix="img"):
    # copy selected image file into dest_dir with a timestamped name
    try:
        src = Path(source_path)
        ext = src.suffix
        fn = f"{prefix}_{datetime.now().strftime('%Y%m%d_%H%M%S')}{ext}"
        dest = dest_dir / fn
        shutil.copy2(src, dest)
        return str(dest)
    except Exception as e:
        print("save_image_file error:", e)
        return None

def generate_invoice_pdf(sale_row, sale_items, invoice_no, out_path, logo_path=None):
    """
    sale_row: dict with sale meta (customer name, phone, date, total, paid, remaining)
    sale_items: list of dicts [{name, qty, price, subtotal}, ...]
    out_path: output PDF path (string)
    """
    if not REPORTLAB_AVAILABLE:
        raise RuntimeError("reportlab not available")

    c = rl_canvas.Canvas(out_path, pagesize=A4)
    width, height = A4
    margin = 20 * mm
    y = height - margin

    # logo
    if logo_path and Path(logo_path).exists():
        try:
            c.drawImage(str(logo_path), margin, y - 25*mm, width=40*mm, preserveAspectRatio=True, mask='auto')
        except Exception:
            pass

    c.setFont("Helvetica-Bold", 14)
    c.drawRightString(width - margin, y, APP_NAME)
    y -= 12*mm

    c.setFont("Helvetica", 10)
    c.drawRightString(width - margin, y, f"التاريخ: {sale_row.get('date')}")
    y -= 6*mm
    c.drawRightString(width - margin, y, f"الزبون: {sale_row.get('name')} - {sale_row.get('phone')}")
    y -= 10*mm

    # table header
    c.setFont("Helvetica-Bold", 10)
    c.drawString(margin, y, "المنتج")
    c.drawRightString(width - margin - 80, y, "الكمية")
    c.drawRightString(width - margin - 40, y, "السعر")
    c.drawRightString(width - margin, y, "الإجمالي")
    y -= 6*mm
    c.setFont("Helvetica", 10)
    for it in sale_items:
        c.drawString(margin, y, it.get('name'))
        c.drawRightString(width - margin - 80, y, str(it.get('qty')))
        c.drawRightString(width - margin - 40, y, str(it.get('price')))
        c.drawRightString(width - margin, y, str(it.get('subtotal')))
        y -= 6*mm
        if y < margin + 40*mm:
            c.showPage()
            y = height - margin

    y -= 6*mm
    c.setFont("Helvetica-Bold", 11)
    c.drawRightString(width - margin, y, f"الإجمالي: {sale_row.get('total')}")
    y -= 8*mm
    c.drawRightString(width - margin, y, f"المدفوع: {sale_row.get('paid')}")
    y -= 8*mm
    c.drawRightString(width - margin, y, f"المتبقي: {sale_row.get('remaining')}")
    y -= 12*mm

    # QR code with invoice number or link
    if QRCODE_AVAILABLE:
        qr = qrcode.QRCode(box_size=4, border=2)
        qr_data = f"Invoice:{invoice_no}|Customer:{sale_row.get('name')}|Total:{sale_row.get('total')}"
        qr.add_data(qr_data)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        bio = io.BytesIO()
        img.save(bio, format='PNG'); bio.seek(0)
        # draw image
        try:
            c.drawImage(bio, margin, y - 30*mm, width=30*mm, height=30*mm, mask='auto')
        except Exception:
            pass

    c.showPage()
    c.save()
    return out_path

# ---------------- Animated / interactive button ----------------
class AnimatedButton(QPushButton):
    def __init__(self, text="", parent=None, role="primary", pulse_scale=1.06, anim_ms=350):
        super().__init__(text, parent)
        self.setProperty("role", role)
        self._pulse_scale = pulse_scale
        self._anim_ms = anim_ms
        self._orig_rect = None
        self._pressed_anim = None

        # تأثير الظل (ثابت وآمن)
        shadow = QGraphicsDropShadowEffect(blurRadius=12, xOffset=0, yOffset=3)
        shadow.setColor(Qt.black)
        self._shadow = shadow
        self.setGraphicsEffect(self._shadow)
        self._shadow.setEnabled(False)

        self.setMouseTracking(True)

    def enterEvent(self, ev):
        """تفعيل الظل عند مرور الماوس"""
        if self._shadow:
            self._shadow.setEnabled(True)
        super().enterEvent(ev)

    def leaveEvent(self, ev):
        """إلغاء الظل عند مغادرة الماوس"""
        if self._shadow:
            self._shadow.setEnabled(False)
        super().leaveEvent(ev)

    def mousePressEvent(self, ev):
        """تأثير النبض عند الضغط بدون تضخيم متكرر"""
        if self._pressed_anim and self._pressed_anim.state() == QPropertyAnimation.Running:
            return  # تجاهل الضغط أثناء الحركة

        if not self._orig_rect:
            self._orig_rect = self.geometry()

        start = self._orig_rect  # استخدم الحجم الأصلي دائمًا
        w, h = start.width(), start.height()
        new_w, new_h = int(w * self._pulse_scale), int(h * self._pulse_scale)
        dx, dy = (new_w - w) // 2, (new_h - h) // 2
        target = QRect(start.x() - dx, start.y() - dy, new_w, new_h)

        anim = QPropertyAnimation(self, b"geometry")
        anim.setDuration(int(self._anim_ms / 2))
        anim.setStartValue(start)
        anim.setEndValue(target)
        anim.setEasingCurve(QEasingCurve.OutQuad)

        # عند الانتهاء ارجع للحجم الأصلي
        anim.finished.connect(lambda: self._restore_geometry(start))
        anim.start()
        self._pressed_anim = anim

        super().mousePressEvent(ev)


    def _restore_geometry(self, orig):
        """استعادة حجم الزر بعد النبض"""
        anim = QPropertyAnimation(self, b"geometry")
        anim.setDuration(int(self._anim_ms / 2))
        anim.setStartValue(self.geometry())
        anim.setEndValue(orig)
        anim.setEasingCurve(QEasingCurve.InQuad)
        anim.start()


# ---------------- Customer Detail Dialog (show tests, add test, upload image) ----------------
class CustomerDetailDialog(QDialog):
    def __init__(self, customer_id, parent=None):
        super().__init__(parent)
        self.customer_id = customer_id
        self.setWindowTitle("تفاصيل العميل")
        self.setMinimumSize(700, 500)
        self.setLayoutDirection(Qt.RightToLeft)
        self.build_ui()
        self.load_data()

    def build_ui(self):
        main = QVBoxLayout()
        # top info
        h = QHBoxLayout()
        self.lbl_name = QLabel("")
        self.lbl_info = QLabel("")
        h.addWidget(self.lbl_name); h.addWidget(self.lbl_info)
        main.addLayout(h)

        # image + upload
        img_row = QHBoxLayout()
        self.img_label = QLabel()
        self.img_label.setFixedSize(140, 140)
        self.img_label.setStyleSheet("border:1px solid #e6eef8; background:white;")
        img_row.addWidget(self.img_label)
        btn_upload = AnimatedButton("📸 رفع صورة العميل", role="light")
        btn_upload.clicked.connect(self.on_upload_image)
        img_row.addWidget(btn_upload)
        img_row.addStretch()
        main.addLayout(img_row)

        # vision tests list and add form
        grp = QGroupBox("سجل فحص النظر")
        g_layout = QVBoxLayout()
        self.tests_table = QTableWidget(0,6)
        self.tests_table.setHorizontalHeaderLabels(['ID','التاريخ','R (SPH/CYL/AX)','L (SPH/CYL/AX)','ملاحظات','تاريخ الفحص القادم'])
        self.tests_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        g_layout.addWidget(self.tests_table)

        form = QFormLayout()
        self.v_right_sph = QLineEdit(); self.v_right_cyl = QLineEdit(); self.v_right_axis = QLineEdit()
        self.v_left_sph = QLineEdit(); self.v_left_cyl = QLineEdit(); self.v_left_axis = QLineEdit()
        self.v_notes = QTextEdit(); self.v_notes.setFixedHeight(70)
        self.v_next = QDateEdit(); self.v_next.setCalendarPopup(True); self.v_next.setDate(QDate.currentDate().addDays(365))
        form.addRow("يمين SPH:", self.v_right_sph); form.addRow("يمين CYL:", self.v_right_cyl); form.addRow("يمين AXIS:", self.v_right_axis)
        form.addRow("يسار SPH:", self.v_left_sph); form.addRow("يسار CYL:", self.v_left_cyl); form.addRow("يسار AXIS:", self.v_left_axis)
        form.addRow("ملاحظات الطبيب:", self.v_notes); form.addRow("تاريخ الفحص القادم:", self.v_next)
        g_layout.addLayout(form)
        btn_add_test = AnimatedButton("حفظ فحص النظر", role="primary"); btn_add_test.clicked.connect(self.save_test)
        g_layout.addWidget(btn_add_test)
        grp.setLayout(g_layout)
        main.addWidget(grp)

        # close
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.rejected.connect(self.reject)
        main.addWidget(bb)
        self.setLayout(main)

    def load_data(self):
        conn = sqlite3.connect(DB_FILE); c = conn.cursor()
        c.execute('SELECT name, age, phone, birth_date, image_path FROM customers WHERE id=?', (self.customer_id,))
        row = c.fetchone()
        if row:
            name, age, phone, birth_date, image_path = row
            self.lbl_name.setText(f"<b>{name}</b>")
            self.lbl_info.setText(f"العمر: {age} — هاتف: {phone} — تاريخ الميلاد: {birth_date or '-'}")
            if image_path and Path(image_path).exists():
                pix = QPixmap(str(image_path)).scaled(self.img_label.width(), self.img_label.height(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
                self.img_label.setPixmap(pix)
            else:
                self.img_label.setText("لا توجد صورة")
        # load tests
        c.execute('SELECT id, date, right_sph, right_cyl, right_axis, left_sph, left_cyl, left_axis, notes, next_exam_date FROM vision_tests WHERE customer_id=? ORDER BY date DESC', (self.customer_id,))
        rows = c.fetchall(); conn.close()
        self.tests_table.setRowCount(0)
        for r in rows:
            row_idx = self.tests_table.rowCount(); self.tests_table.insertRow(row_idx)
            tid = r[0]; date_s = r[1]
            r_s = f"{r[2]}/{r[3]}/{r[4]}"
            l_s = f"{r[5]}/{r[6]}/{r[7]}"
            notes = r[8] or ''
            next_d = r[9] or ''
            self.tests_table.setItem(row_idx, 0, QTableWidgetItem(str(tid)))
            self.tests_table.setItem(row_idx, 1, QTableWidgetItem(date_s))
            self.tests_table.setItem(row_idx, 2, QTableWidgetItem(r_s))
            self.tests_table.setItem(row_idx, 3, QTableWidgetItem(l_s))
            self.tests_table.setItem(row_idx, 4, QTableWidgetItem(notes))
            self.tests_table.setItem(row_idx, 5, QTableWidgetItem(next_d))

    def save_test(self):
        try:
            right_sph = float(self.v_right_sph.text() or 0)
            right_cyl = float(self.v_right_cyl.text() or 0)
            right_axis = float(self.v_right_axis.text() or 0)
            left_sph = float(self.v_left_sph.text() or 0)
            left_cyl = float(self.v_left_cyl.text() or 0)
            left_axis = float(self.v_left_axis.text() or 0)
        except ValueError:
            QMessageBox.warning(self, 'خطأ', 'أدخل قيمًا صحيحة للأرقام'); return
        notes = self.v_notes.toPlainText().strip()
        next_d = self.v_next.date().toString("yyyy-MM-dd")
        date_now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        conn = sqlite3.connect(DB_FILE); c = conn.cursor()
        c.execute('INSERT INTO vision_tests (customer_id, date, right_sph, right_cyl, right_axis, left_sph, left_cyl, left_axis, notes, next_exam_date) VALUES (?,?,?,?,?,?,?,?,?,?)',
                  (self.customer_id, date_now, right_sph, right_cyl, right_axis, left_sph, left_cyl, left_axis, notes, next_d))
        # also create reminder for next exam
        c.execute('INSERT INTO reminders (sale_id, remind_date, type) VALUES (?,?,?)', (self.customer_id, next_d, 'next_exam'))
        conn.commit(); conn.close()
        QMessageBox.information(self, 'تم', 'تم حفظ فحص النظر وإنشاء التذكير.')
        self.load_data()

    def on_upload_image(self):
        path, _ = QFileDialog.getOpenFileName(self, 'اختر صورة العميل', '', 'Image Files (*.png *.jpg *.jpeg *.bmp)')
        if not path: return
        saved = save_image_file(path, IMAGES_CUSTOMERS, prefix=f"cust_{self.customer_id}")
        if not saved:
            QMessageBox.warning(self, 'خطأ', 'فشل حفظ الصورة'); return
        conn = sqlite3.connect(DB_FILE); c = conn.cursor()
        c.execute('UPDATE customers SET image_path=? WHERE id=?', (saved, self.customer_id))
        conn.commit(); conn.close()
        QMessageBox.information(self, 'تم', 'تم رفع الصورة.')
        self.load_data()

# ---------------- Main Window ----------------
class MainWindow(QMainWindow):
    def __init__(self, username):
        super().__init__()
        self.username = username
        self.setWindowTitle(f"{APP_NAME} — {username}")
        self.setMinimumSize(1200, 760)
        self.setStyleSheet(APP_STYLE)
        self.setLayoutDirection(Qt.RightToLeft)
        self._build_ui()
        self.reminder_timer = QTimer(self); self.reminder_timer.timeout.connect(self.load_reminders); self.reminder_timer.start(60*1000)
        self.load_all()

    def _build_ui(self):
        central = QWidget()
        main_h = QHBoxLayout()
        central.setLayout(main_h)
        self.setCentralWidget(central)

        # Sidebar
        sidebar = QFrame(); sidebar.setObjectName('sidebar'); sidebar.setFixedWidth(260)
        sb_layout = QVBoxLayout(); sidebar.setLayout(sb_layout)
        title = QLabel(APP_NAME); title.setStyleSheet("font-size:14pt; font-weight:bold; color:#0f172a;"); title.setWordWrap(True)
        title.setAlignment(Qt.AlignCenter)
        sb_layout.addWidget(title)
        sb_layout.addSpacing(6)

        self.menu = QListWidget(); self.menu.setFixedWidth(240)
        items = [
            ("🏠 الصفحة الرئيسية", "dashboard"),
            ("💰 المبيعات", "sales"),
            ("👥 العملاء", "customers"),
            ("👓 العدسات", "lenses"),
            ("📦 المخزون", "inventory"),
            ("🔔 التذكيرات", "reminders"),
            ("📊 التقارير", "reports"),
            ("⚙️ الإعدادات", "settings")
        ]
        for label, key in items:
            it = QListWidgetItem(label)
            it.setData(Qt.UserRole, key)
            self.menu.addItem(it)
        self.menu.currentRowChanged.connect(self.switch_page)
        sb_layout.addWidget(self.menu)
        sb_layout.addStretch()

        # Right container (topbar + stack)
        right_container = QVBoxLayout()

        # Topbar
        topbar = QFrame(); topbar.setObjectName('topbar'); topbar.setFixedHeight(TOP_BAR_HEIGHT)
        tb_layout = QHBoxLayout(); tb_layout.setContentsMargins(12, 6, 12, 6); tb_layout.setSpacing(12); topbar.setLayout(tb_layout)
        self.page_title = QLabel("الصفحة الرئيسية"); self.page_title.setStyleSheet("font-weight:bold; font-size:14pt;")
        tb_layout.addWidget(self.page_title)
        tb_layout.addStretch()

        logo_path = Path(LOGO_FILE)
        if logo_path.exists():
            pix = QPixmap(str(logo_path)).scaledToHeight(36, Qt.SmoothTransformation)
            logo_lbl = QLabel(); logo_lbl.setPixmap(pix); logo_lbl.setAlignment(Qt.AlignCenter)
            tb_layout.addWidget(logo_lbl)

        self.user_badge = QLabel(f"👤 مرحبًا، {self.username}")
        self.user_badge.setObjectName('userBadge')
        self.user_badge.setStyleSheet("QLabel#userBadge { background: #E8F1FB; color: #0078D7; border-radius: 12px; padding: 6px 12px; font-weight:600; }")
        tb_layout.addWidget(self.user_badge)
        tb_layout.addSpacing(8)

        self.btn_quick = AnimatedButton("🔄 نسخة سريعة", role="primary")
        self.btn_quick.setFixedSize(TOP_BUTTON_WIDTH, TOP_BUTTON_HEIGHT)
        self.btn_quick.clicked.connect(self.on_quick_backup)
        tb_layout.addWidget(self.btn_quick)

        self.btn_logout = AnimatedButton("🚪 تسجيل الخروج", role="danger")
        self.btn_logout.setFixedSize(TOP_BUTTON_WIDTH, TOP_BUTTON_HEIGHT)
        self.btn_logout.clicked.connect(self.on_logout)
        tb_layout.addWidget(self.btn_logout)

        # pages stack
        self.stack = QStackedWidget()
        self.page_dashboard = self._page_dashboard()
        self.page_sales = self._page_sales()
        self.page_customers = self._page_customers()
        self.page_lenses = self._page_lenses()
        self.page_inventory = self._page_inventory()
        self.page_reminders = self._page_reminders()
        self.page_reports = self._page_reports()
        self.page_settings = self._page_settings()

        for p in [self.page_dashboard, self.page_sales, self.page_customers, self.page_lenses, self.page_inventory, self.page_reminders, self.page_reports, self.page_settings]:
            self.stack.addWidget(p)

        right_container.addWidget(topbar)
        right_container.addWidget(self.stack)

        main_h.addWidget(sidebar)
        main_h.addLayout(right_container)

        # default
        self.menu.setCurrentRow(0)

    # ---------------- Pages ----------------
    def _page_dashboard(self):
        p = QWidget(); layout = QVBoxLayout(); p.setLayout(layout)

        # top analytics row
        row = QHBoxLayout()
        self.card_total = self._make_card("إجمالي اليوم", "0")
        self.card_count = self._make_card("عدد المبيعات اليوم", "0")
        self.card_new = self._make_card("عملاء جدد اليوم", "0")
        row.addWidget(self.card_total); row.addWidget(self.card_count); row.addWidget(self.card_new)
        layout.addLayout(row)

        # analytics row 2
        row2 = QHBoxLayout()
        self.card_monthly = self._make_card("إيرادات هذا الشهر", "0")
        self.card_toplens = self._make_card("العدسة الأكثر مبيعًا", "-")
        self.card_avgsale = self._make_card("متوسط سعر البيع", "0")
        self.card_lowstock = self._make_card("أجزاء منخفضة بالمخزون", "0")
        row2.addWidget(self.card_monthly); row2.addWidget(self.card_toplens); row2.addWidget(self.card_avgsale); row2.addWidget(self.card_lowstock)
        layout.addLayout(row2)

        layout.addSpacing(12)
        btn_refresh = AnimatedButton("تحديث الإحصائيات", role="light")
        btn_refresh.clicked.connect(self.update_dashboard)
        layout.addWidget(btn_refresh)

        # optional chart area (if charts available)
        if CHARTS_AVAILABLE:
            self.chart_view = QChartView()
            layout.addWidget(self.chart_view)

        layout.addStretch()
        return p

    def _make_card(self, title, value):
        f = QFrame(); f.setObjectName('card'); f.setProperty('class', 'card')
        v = QVBoxLayout(); lbl = QLabel(title); lbl.setStyleSheet("font-weight:bold; color:#1e3a8a;"); val = QLabel(value); val.setStyleSheet("font-size:16pt;")
        v.addWidget(lbl); v.addWidget(val)
        f.setLayout(v); f.value_label = val
        return f

    def _page_sales(self):
        p = QWidget(); layout = QVBoxLayout(); p.setLayout(layout)

        # Filters row (advanced)
        filter_row = QHBoxLayout()
        self.filter_from = QDateEdit(); self.filter_from.setCalendarPopup(True)
        self.filter_to = QDateEdit(); self.filter_to.setCalendarPopup(True)
        # default: this month's start/end
        today = QDate.currentDate()
        first = QDate(today.year(), today.month(), 1)
        self.filter_from.setDate(first)
        self.filter_to.setDate(today)

        self.filter_lens = QComboBox()
        self.filter_lens.addItem("الكل")
        self.filter_payment = QComboBox()
        self.filter_payment.addItems(["الكل", "مدفوع بالكامل", "باقي عليه"])
        btn_filter = AnimatedButton("تطبيق الفلترة", role="muted")
        btn_filter.clicked.connect(self.apply_filters)

        filter_row.addWidget(QLabel("من:")); filter_row.addWidget(self.filter_from)
        filter_row.addWidget(QLabel("إلى:")); filter_row.addWidget(self.filter_to)
        filter_row.addWidget(QLabel("نوع العدسة:")); filter_row.addWidget(self.filter_lens)
        filter_row.addWidget(QLabel("حالة الدفع:")); filter_row.addWidget(self.filter_payment)
        filter_row.addWidget(btn_filter)
        layout.addLayout(filter_row)

        # Sales form
        form = QFormLayout()
        self.s_name = QLineEdit()
        self.s_age = QSpinBox(); self.s_age.setRange(0,120)
        self.s_lens = QComboBox()
        # new: select inventory item (if available)
        self.s_inventory = QComboBox()
        self.s_qty = QSpinBox(); self.s_qty.setRange(1,100); self.s_qty.setValue(1)
        self.s_total = QLineEdit(); self.s_paid = QLineEdit(); self.s_phone = QLineEdit()
        self.s_notes = QTextEdit(); self.s_notes.setFixedHeight(80)
        form.addRow("اسم الزبون:", self.s_name)
        form.addRow("العمر:", self.s_age)
        form.addRow("نوع العدسة (اسم):", self.s_lens)
        form.addRow("صنف من المخزون (اختياري):", self.s_inventory)
        form.addRow("الكمية:", self.s_qty)
        form.addRow("المبلغ الكلي:", self.s_total)
        form.addRow("الواصل:", self.s_paid)
        form.addRow("رقم الزبون:", self.s_phone)
        form.addRow("ملاحظات:", self.s_notes)
        btn_save = AnimatedButton("💾 حفظ البيع وإنشاء فاتورة", role="primary"); btn_save.clicked.connect(self.save_sale)
        layout.addLayout(form); layout.addWidget(btn_save)

        self.table_sales = QTableWidget(0,10)
        self.table_sales.setHorizontalHeaderLabels(['ID','الزبون','العمر','العدسة','التاريخ','المبلغ','الواصل','المتبقي','الهاتف','فاتورة'])
        self.table_sales.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        layout.addWidget(self.table_sales)
        return p

    def _page_customers(self):
        p = QWidget(); layout = QVBoxLayout(); p.setLayout(layout)
        top = QHBoxLayout()
        self.search_customer = QLineEdit(); self.search_customer.setPlaceholderText('بحث بالاسم أو الهاتف')
        btn_search = AnimatedButton('🔎 بحث', role="muted"); btn_search.clicked.connect(self.search_customers)
        btn_add = AnimatedButton('➕ إضافة عميل جديد', role="light"); btn_add.clicked.connect(self.add_customer_dialog)
        top.addWidget(self.search_customer); top.addWidget(btn_search); top.addWidget(btn_add)
        layout.addLayout(top)
        self.table_customers = QTableWidget(0,10)
        self.table_customers.setHorizontalHeaderLabels(['ID','الاسم','العمر','العدسة','التاريخ','المبلغ','الواصل','المتبقي','الهاتف','صورة'])
        self.table_customers.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table_customers.cellDoubleClicked.connect(self.on_customer_doubleclick)
        layout.addWidget(self.table_customers)
        return p

    def _page_lenses(self):
        p = QWidget(); layout = QVBoxLayout(); p.setLayout(layout)
        row = QHBoxLayout()
        self.new_lens = QLineEdit(); self.new_lens.setPlaceholderText('اسم العدسة')
        btn_add = AnimatedButton('➕ إضافة عدسة', role="light"); btn_add.clicked.connect(self.add_lens)
        row.addWidget(self.new_lens); row.addWidget(btn_add)
        layout.addLayout(row)
        self.table_lenses = QTableWidget(0,3)
        self.table_lenses.setHorizontalHeaderLabels(['ID','الاسم','صورة'])
        self.table_lenses.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        layout.addWidget(self.table_lenses)
        return p

    def _page_inventory(self):
        p = QWidget(); layout = QVBoxLayout(); p.setLayout(layout)
        # add product form
        form_row = QGridLayout()
        self.i_type = QComboBox(); self.i_type.addItems(['lens', 'frame'])
        self.i_name = QLineEdit(); self.i_brand = QLineEdit(); self.i_size = QLineEdit()
        self.i_qty = QSpinBox(); self.i_qty.setRange(0,10000); self.i_price = QLineEdit()
        btn_img = AnimatedButton('📸 إضافة صورة', role="muted"); btn_img.clicked.connect(self.add_inventory_image)
        self.i_image_label = QLabel("لا توجد صورة"); self.i_image_label.setFixedSize(100,80)
        btn_add = AnimatedButton('➕ إضافة للمخزون', role="light"); btn_add.clicked.connect(self.add_inventory_item)
        form_row.addWidget(QLabel("النوع:"), 0, 0); form_row.addWidget(self.i_type, 0, 1)
        form_row.addWidget(QLabel("الاسم:"), 0, 2); form_row.addWidget(self.i_name, 0, 3)
        form_row.addWidget(QLabel("الماركة:"), 1, 0); form_row.addWidget(self.i_brand, 1, 1)
        form_row.addWidget(QLabel("المقاس:"), 1, 2); form_row.addWidget(self.i_size, 1, 3)
        form_row.addWidget(QLabel("الكمية:"), 2, 0); form_row.addWidget(self.i_qty, 2, 1)
        form_row.addWidget(QLabel("السعر:"), 2, 2); form_row.addWidget(self.i_price, 2, 3)
        form_row.addWidget(btn_img, 3, 0); form_row.addWidget(self.i_image_label, 3, 1)
        form_row.addWidget(btn_add, 3, 3)
        layout.addLayout(form_row)
        self.table_inventory = QTableWidget(0,7)
        self.table_inventory.setHorizontalHeaderLabels(['ID','النوع','الاسم','الماركة','المقاس','الكمية','السعر'])
        self.table_inventory.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        layout.addWidget(self.table_inventory)
        return p

    def _page_reminders(self):
        p = QWidget(); layout = QVBoxLayout(); p.setLayout(layout)

        # Upcoming reminders
        layout.addWidget(QLabel("🔜 التذكيرات القادمة"))
        self.table_upcoming = QTableWidget(0,7)
        self.table_upcoming.setHorizontalHeaderLabels(['ID','SaleID','الزبون / نوع','تاريخ التذكير','نوع','إرسال واتساب','ملاحظات'])
        self.table_upcoming.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        layout.addWidget(self.table_upcoming)

        layout.addSpacing(8)
        layout.addWidget(QLabel("🔔 التذكيرات المستحقة"))
        self.table_reminders = QTableWidget(0,7)
        self.table_reminders.setHorizontalHeaderLabels(['ID','SaleID','الزبون / نوع','تاريخ التذكير','نوع','إرسال واتساب','ملاحظات'])
        self.table_reminders.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        layout.addWidget(self.table_reminders)

        layout.addSpacing(12)
        # birthdays today
        layout.addWidget(QLabel("🎂 أعياد الميلاد اليوم"))
        self.table_bdays = QTableWidget(0,4)
        self.table_bdays.setHorizontalHeaderLabels(['ID','الاسم','الهاتف','تاريخ الميلاد'])
        self.table_bdays.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        layout.addWidget(self.table_bdays)
        return p

    def _page_reports(self):
        p = QWidget(); layout = QVBoxLayout(); p.setLayout(layout)
        row = QHBoxLayout()
        btn_day = AnimatedButton('تقرير اليوم', role="muted"); btn_day.clicked.connect(self.report_daily)
        btn_month = AnimatedButton('تقرير الشهر', role="muted"); btn_month.clicked.connect(self.report_monthly)
        btn_export = AnimatedButton('تصدير مبيعات CSV', role="light"); btn_export.clicked.connect(self.export_sales_csv)
        row.addWidget(btn_day); row.addWidget(btn_month); row.addWidget(btn_export)
        layout.addLayout(row)
        self.report_output = QTextEdit(); self.report_output.setReadOnly(True)
        layout.addWidget(self.report_output)
        return p

    def _page_settings(self):
        p = QWidget(); layout = QVBoxLayout(); p.setLayout(layout)
        # Backup buttons
        btn_quick = AnimatedButton("🔄 نسخة سريعة (محلية)", role="primary"); btn_quick.clicked.connect(self.on_quick_backup)
        btn_backup = AnimatedButton("💾 إنشاء نسخة احتياطية (حفظ)", role="light"); btn_backup.clicked.connect(self.on_backup_saveas)
        btn_restore = AnimatedButton("📂 استعادة نسخة احتياطية", role="muted"); btn_restore.clicked.connect(self.on_restore)
        layout.addWidget(btn_quick); layout.addWidget(btn_backup); layout.addWidget(btn_restore)

        layout.addSpacing(12)

        # --- Clinic info group ---
        grp = QGroupBox("🩺 معلومات المركز")
        g_layout = QFormLayout()

        # load current clinic name (fallback to APP_NAME if empty)
        try:
            clinic_current = CLINIC_NAME or APP_NAME
        except Exception:
            clinic_current = APP_NAME

        self.inp_clinic_name = QLineEdit(); self.inp_clinic_name.setPlaceholderText("اسم المركز")
        self.inp_clinic_name.setText(clinic_current if CLINIC_NAME else "")
        g_layout.addRow("اسم المركز:", self.inp_clinic_name)

        btn_save_name = AnimatedButton("💾 حفظ الاسم", role="light")
        def on_save_name():
            newname = self.inp_clinic_name.text().strip()
            cp = configparser.ConfigParser()
            # ensure config exists and read then update
            if Path(CONFIG_FILE).exists():
                cp.read(CONFIG_FILE, encoding='utf-8')
            if 'DEFAULT' not in cp:
                cp['DEFAULT'] = {}
            cp['DEFAULT']['clinic_name'] = newname
            with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                cp.write(f)
            # update runtime CLINIC_NAME variable and notify user
            global CLINIC_NAME
            CLINIC_NAME = newname
            QMessageBox.information(self, 'تم', 'تم حفظ اسم المركز.')
        btn_save_name.clicked.connect(on_save_name)

        row = QHBoxLayout(); row.addWidget(btn_save_name); row.addStretch()
        g_layout.addRow(row)

        grp.setLayout(g_layout)
        layout.addWidget(grp)

        layout.addStretch()
        return p

    # ---------------- Actions & Data ----------------
    def switch_page(self, index):
        item = self.menu.item(index)
        if not item: return
        key = item.data(Qt.UserRole)
        title = item.text()
        self.page_title.setText(title)
        self.stack.setCurrentIndex(index)
        if key == "dashboard":
            self.update_dashboard()
        elif key == "sales":
            self.load_sales(); self.populate_lens_combo(); self.populate_inventory_combo()
        elif key == "customers":
            self.load_customers()
        elif key == "lenses":
            self.load_lenses()
        elif key == "inventory":
            self.load_inventory()
        elif key == "reminders":
            self.load_reminders()

    def load_all(self):
        self.update_dashboard(); self.load_lenses(); self.load_sales(); self.load_customers(); self.populate_lens_combo(); self.load_inventory(); self.populate_inventory_combo(); self.load_reminders()

    # --- Sales & reminders & invoices
    def save_sale(self):
        name = self.s_name.text().strip()
        if not name:
            QMessageBox.warning(self, 'خطأ', 'ادخل اسم الزبون'); return
        age = int(self.s_age.value())
        lens = self.s_lens.currentText()
        inv_selection = self.s_inventory.currentText()
        qty = int(self.s_qty.value())
        try:
            total = float(self.s_total.text() or 0)
            paid = float(self.s_paid.text() or 0)
        except ValueError:
            QMessageBox.warning(self, 'خطأ', 'ادخل أرقام صحيحة للمبالغ'); return
        remaining = total - paid
        phone = self.s_phone.text().strip()
        notes = self.s_notes.toPlainText().strip()
        date = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        conn = sqlite3.connect(DB_FILE); c = conn.cursor()
        c.execute('INSERT INTO customers (name,age,lens_type,date,total,paid,remaining,phone,notes) VALUES (?,?,?,?,?,?,?,?,?)',
                  (name, age, lens, date, total, paid, remaining, phone, notes))
        sale_id = c.lastrowid

        # create reminders: 3days and 4 months as before
        r1 = (sale_id, (datetime.now() + timedelta(days=3)).strftime('%Y-%m-%d'), '3days')
        r2 = (sale_id, (datetime.now() + timedelta(days=120)).strftime('%Y-%m-%d'), '4months')
        c.execute('INSERT INTO reminders (sale_id, remind_date, type) VALUES (?,?,?)', r1)
        c.execute('INSERT INTO reminders (sale_id, remind_date, type) VALUES (?,?,?)', r2)

        # if inventory item selected, reduce quantity
        if inv_selection:
            # find inventory by name
            c.execute('SELECT id, quantity, price FROM inventory WHERE name=? LIMIT 1', (inv_selection,))
            row = c.fetchone()
            if row:
                inv_id, cur_qty, price = row
                new_qty = max(0, cur_qty - qty)
                c.execute('UPDATE inventory SET quantity=? WHERE id=?', (new_qty, inv_id))
                # low stock? we'll show in dashboard
        conn.commit()

        # generate invoice PDF
        try:
            invoice_no = f"INV{datetime.now().strftime('%Y%m%d%H%M%S')}_{sale_id}"
            invoice_file = INVOICES_DIR / f"{invoice_no}.pdf"
            sale_meta = {'name': name, 'phone': phone, 'date': date, 'total': total, 'paid': paid, 'remaining': remaining}
            # items list - create at least one item entry
            sale_items = []
            if inv_selection:
                sale_items.append({'name': inv_selection, 'qty': qty, 'price': float(self.i_price.text() or price if hasattr(self, 'i_price') else 0), 'subtotal': round(qty * (float(self.i_price.text() or price or 0)), 2)})
            else:
                # fallback: use lens name as single item
                sale_items.append({'name': lens or "بيع", 'qty': 1, 'price': total, 'subtotal': total})
            if REPORTLAB_AVAILABLE:
                generate_invoice_pdf(sale_meta, sale_items, invoice_no, str(invoice_file), logo_path=LOGO_FILE if Path(LOGO_FILE).exists() else None)
                # save invoice metadata
                c.execute('INSERT INTO invoices (sale_id, invoice_no, file_path, date, total) VALUES (?,?,?,?,?)', (sale_id, invoice_no, str(invoice_file), date, total))
                conn.commit()
            else:
                invoice_file = None
        except Exception as e:
            print("Invoice generation failed:", e)
            invoice_file = None

        conn.close()

        QMessageBox.information(self, 'تم', 'تم حفظ البيع وإنشاء التذكيرات' + ('. تم إنشاء الفاتورة.' if invoice_file else '.'))
        # clear form
        self.s_name.clear(); self.s_total.clear(); self.s_paid.clear(); self.s_phone.clear(); self.s_notes.clear()
        self.load_sales(); self.load_reminders(); self.update_dashboard(); self.load_inventory()
        self.populate_inventory_combo()

    def load_sales(self):
        conn = sqlite3.connect(DB_FILE); c = conn.cursor()
        q = '''SELECT id, name, age, lens_type, date, total, paid, remaining, phone FROM customers ORDER BY date DESC'''
        c.execute(q); rows = c.fetchall(); conn.close()
        self.table_sales.setRowCount(0)
        for r in rows:
            row = self.table_sales.rowCount(); self.table_sales.insertRow(row)
            for i, val in enumerate(r):
                self.table_sales.setItem(row, i, QTableWidgetItem(str(val)))
            # invoice lookup
            sale_id = r[0]
            conn = sqlite3.connect(DB_FILE); c = conn.cursor()
            c.execute('SELECT file_path FROM invoices WHERE sale_id=? ORDER BY id DESC LIMIT 1', (sale_id,))
            inv = c.fetchone(); conn.close()
            if inv and inv[0]:
                btn = AnimatedButton("عرض فاتورة", role="light")
                def make_inv_handler(path=inv[0]):
                    def handler():
                        if Path(path).exists():
                            webbrowser.open(str(Path(path).absolute()))
                        else:
                            QMessageBox.warning(None, 'خطأ', 'ملف الفاتورة غير موجود')
                    return handler
                btn.clicked.connect(make_inv_handler())
                self.table_sales.setCellWidget(row, 9, btn)

    # --- Customers
    def load_customers(self):
        conn = sqlite3.connect(DB_FILE); c = conn.cursor()
        c.execute('SELECT id, name, age, lens_type, date, total, paid, remaining, phone, image_path FROM customers ORDER BY id DESC')
        rows = c.fetchall(); conn.close()
        self.table_customers.setRowCount(0)
        for r in rows:
            row = self.table_customers.rowCount(); self.table_customers.insertRow(row)
            for i, val in enumerate(r):
                if i == 9:
                    # image column - show text or small indicator
                    item = QTableWidgetItem("✔" if val else "-")
                    self.table_customers.setItem(row, i, item)
                else:
                    self.table_customers.setItem(row, i, QTableWidgetItem(str(val)))

    def search_customers(self):
        term = self.search_customer.text().strip()
        conn = sqlite3.connect(DB_FILE); c = conn.cursor()
        q = "SELECT id, name, age, lens_type, date, total, paid, remaining, phone, image_path FROM customers WHERE name LIKE ? OR phone LIKE ? ORDER BY id DESC"
        c.execute(q, (f"%{term}%", f"%{term}%"))
        rows = c.fetchall(); conn.close()
        self.table_customers.setRowCount(0)
        for r in rows:
            row = self.table_customers.rowCount(); self.table_customers.insertRow(row)
            for i, val in enumerate(r):
                if i == 9:
                    item = QTableWidgetItem("✔" if val else "-")
                    self.table_customers.setItem(row, i, item)
                else:
                    self.table_customers.setItem(row, i, QTableWidgetItem(str(val)))

    def add_customer_dialog(self):
        # extended dialog to include birth date and optional image
        dlg = QDialog(self)
        dlg.setWindowTitle("إضافة عميل")
        dlg.setLayoutDirection(Qt.RightToLeft)
        layout = QVBoxLayout()
        form = QFormLayout()
        inp_name = QLineEdit(); inp_age = QSpinBox(); inp_age.setRange(0,120)
        inp_birth = QDateEdit(); inp_birth.setCalendarPopup(True); inp_birth.setDate(QDate.currentDate())
        inp_phone = QLineEdit()
        form.addRow("الاسم:", inp_name)
        form.addRow("العمر:", inp_age)
        form.addRow("تاريخ الميلاد:", inp_birth)
        form.addRow("الهاتف:", inp_phone)
        layout.addLayout(form)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(dlg.accept); bb.rejected.connect(dlg.reject)
        layout.addWidget(bb)
        dlg.setLayout(layout)
        if dlg.exec() == QDialog.Accepted:
            name = inp_name.text().strip()
            age = int(inp_age.value())
            birth = inp_birth.date().toString("yyyy-MM-dd")
            phone = inp_phone.text().strip()
            if not name:
                QMessageBox.warning(self, 'تنبيه', 'أدخل اسم العميل'); return
            conn = sqlite3.connect(DB_FILE); c = conn.cursor()
            date = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            c.execute('INSERT INTO customers (name, age, lens_type, date, total, paid, remaining, phone, notes, birth_date, image_path) VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                      (name, age, '', date, 0, 0, 0, phone, '', birth, ''))
            conn.commit(); conn.close()
            self.load_customers()
            QMessageBox.information(self, 'تم', 'تم إضافة العميل.')

    def on_customer_doubleclick(self, row, col):
        cid_item = self.table_customers.item(row, 0)
        if not cid_item: return
        try:
            cid = int(cid_item.text())
            dlg = CustomerDetailDialog(cid, parent=self)
            dlg.exec()
            self.load_customers()
        except Exception:
            pass

    # --- Lenses
    def add_lens(self):
        name = self.new_lens.text().strip()
        if not name:
            QMessageBox.warning(self, 'تنبيه', 'ادخل اسم العدسة'); return
        conn = sqlite3.connect(DB_FILE); c = conn.cursor()
        try:
            c.execute('INSERT INTO lenses (name) VALUES (?)', (name,))
            conn.commit(); conn.close()
            self.new_lens.clear(); QMessageBox.information(self, 'تمت إضافة العدسة')
            self.load_lenses(); self.populate_lens_combo()
        except sqlite3.IntegrityError:
            conn.close(); QMessageBox.warning(self, 'موجود', 'العدسة موجودة بالفعل')

    def load_lenses(self):
        conn = sqlite3.connect(DB_FILE); c = conn.cursor()
        c.execute('SELECT id, name FROM lenses ORDER BY id DESC'); rows = c.fetchall(); conn.close()
        self.table_lenses.setRowCount(0)
        for r in rows:
            row = self.table_lenses.rowCount(); self.table_lenses.insertRow(row)
            self.table_lenses.setItem(row, 0, QTableWidgetItem(str(r[0])))
            self.table_lenses.setItem(row, 1, QTableWidgetItem(str(r[1])))
            self.table_lenses.setItem(row, 2, QTableWidgetItem("-"))

    def populate_lens_combo(self):
        conn = sqlite3.connect(DB_FILE); c = conn.cursor()
        c.execute('SELECT name FROM lenses ORDER BY name'); rows = c.fetchall(); conn.close()
        # for sale form
        self.s_lens.clear()
        self.s_lens.addItem("")  # allow empty
        for r in rows:
            self.s_lens.addItem(r[0])

    # --- Inventory
    def add_inventory_image(self):
        path, _ = QFileDialog.getOpenFileName(self, 'اختر صورة للمنتج', '', 'Image Files (*.png *.jpg *.jpeg *.bmp)')
        if not path: return
        saved = save_image_file(path, IMAGES_INVENTORY, prefix="inv")
        if saved:
            pix = QPixmap(saved).scaled(self.i_image_label.width(), self.i_image_label.height(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self.i_image_label.setPixmap(pix)
            self.i_image_label.image_path = saved
        else:
            QMessageBox.warning(self, 'خطأ', 'فشل حفظ الصورة')

    def add_inventory_item(self):
        t = self.i_type.currentText(); name = self.i_name.text().strip()
        brand = self.i_brand.text().strip(); size = self.i_size.text().strip(); qty = int(self.i_qty.value())
        try:
            price = float(self.i_price.text() or 0)
        except Exception:
            QMessageBox.warning(self, 'خطأ', 'أدخل سعرًا صحيحًا'); return
        image_path = getattr(self.i_image_label, 'image_path', '') or ''
        if not name:
            QMessageBox.warning(self, 'تنبيه', 'ادخل اسم المنتج'); return
        conn = sqlite3.connect(DB_FILE); c = conn.cursor()
        c.execute('INSERT INTO inventory (type, name, brand, size, quantity, price, image_path) VALUES (?,?,?,?,?,?,?)',
                  (t, name, brand, size, qty, price, image_path))
        conn.commit(); conn.close()
        QMessageBox.information(self, 'تم', 'تم إضافة المنتج إلى المخزون')
        self.i_name.clear(); self.i_brand.clear(); self.i_size.clear(); self.i_qty.setValue(0); self.i_price.clear()
        self.i_image_label.clear(); self.i_image_label.setText("لا توجد صورة")
        self.load_inventory(); self.populate_inventory_combo()

    def load_inventory(self):
        conn = sqlite3.connect(DB_FILE); c = conn.cursor()
        c.execute('SELECT id, type, name, brand, size, quantity, price FROM inventory ORDER BY id DESC')
        rows = c.fetchall(); conn.close()
        self.table_inventory.setRowCount(0)
        for r in rows:
            row = self.table_inventory.rowCount(); self.table_inventory.insertRow(row)
            for i, val in enumerate(r):
                self.table_inventory.setItem(row, i, QTableWidgetItem(str(val)))

    def populate_inventory_combo(self):
        conn = sqlite3.connect(DB_FILE); c = conn.cursor()
        c.execute('SELECT name FROM inventory ORDER BY name'); rows = c.fetchall(); conn.close()
        self.s_inventory.clear(); self.s_inventory.addItem("")  # optional
        for r in rows:
            self.s_inventory.addItem(r[0])

    # --- Reminders (smart upcoming + due + birthdays)
    
    def load_reminders(self):
        today = datetime.now().strftime('%Y-%m-%d')
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()

        # Due reminders (today or earlier)
        q_due = """SELECT r.id, r.sale_id, r.remind_date, r.type, r.sent, s.phone, s.name
                     FROM reminders r LEFT JOIN customers s ON r.sale_id=s.id
                     WHERE r.remind_date <= ? AND r.sent=0 ORDER BY r.remind_date ASC"""
        c.execute(q_due, (today,))
        due_rows = c.fetchall()

        # Upcoming reminders (future)
        q_up = """SELECT r.id, r.sale_id, r.remind_date, r.type, r.sent, s.phone, s.name
                    FROM reminders r LEFT JOIN customers s ON r.sale_id=s.id
                    WHERE r.remind_date > ? AND r.sent=0 ORDER BY r.remind_date ASC"""
        c.execute(q_up, (today,))
        up_rows = c.fetchall()

        # Birthdays (match month-day)
        md = datetime.now().strftime('-%m-%d')
        c.execute("SELECT id, name, phone, birth_date FROM customers WHERE birth_date LIKE ?", (f"%{md}",))
        bdays = c.fetchall()
        conn.close()

        clinic = (CLINIC_NAME.strip() if isinstance(CLINIC_NAME, str) else '') or APP_NAME

        # --- Due Reminders ---
        self.table_reminders.setRowCount(0)
        for rid, sale_id, date_s, rtype, sent, phone, cust_name in due_rows:
            label = cust_name or f"ID:{sale_id}"
            row = self.table_reminders.rowCount()
            self.table_reminders.insertRow(row)
            self.table_reminders.setItem(row, 0, QTableWidgetItem(str(rid)))
            self.table_reminders.setItem(row, 1, QTableWidgetItem(str(sale_id)))
            self.table_reminders.setItem(row, 2, QTableWidgetItem(label))
            self.table_reminders.setItem(row, 3, QTableWidgetItem(date_s))
            self.table_reminders.setItem(row, 4, QTableWidgetItem(rtype))
            self.table_reminders.setItem(row, 6, QTableWidgetItem(''))

            btn = AnimatedButton("إرسال واتساب", role="primary")

            def make_handler(phone_num=phone, r_id=rid, r_type=rtype):
                def handler():
                    if r_type == '3days':
                        msg = f'مرحباً! نأمل أن تجربتك في مركز {clinic} كانت رائعة. يسعدنا سماع رأيك أو ملاحظاتك.'
                    elif r_type == '4months':
                        msg = f'مرحباً! نود تذكيرك بزيارة مركز {clinic} لفحص نظرك أو تجديد نظارتك. نرحب بك دائماً.'
                    elif r_type == 'next_exam':
                        msg = f'تذكير بموعد فحص العين القادم في مركز {clinic}. نتطلع لرؤيتك قريباً!'
                    else:
                        msg = f'مرحباً! هذا تذكير من {clinic}.'
                    open_whatsapp(phone_num, msg)
                    conn2 = sqlite3.connect(DB_FILE)
                    c2 = conn2.cursor()
                    c2.execute('UPDATE reminders SET sent=1, status=? WHERE id=?', ('sent', r_id))
                    conn2.commit()
                    conn2.close()
                    QMessageBox.information(None, 'تم', 'تم فتح واتساب وتم وسم التذكير كمُرسل')
                    self.load_reminders()
                return handler

            btn.clicked.connect(make_handler())
            self.table_reminders.setCellWidget(row, 5, btn)

        # --- Upcoming Reminders ---
        self.table_upcoming.setRowCount(0)
        for rid, sale_id, date_s, rtype, sent, phone, cust_name in up_rows:
            label = cust_name or f"ID:{sale_id}"
            row = self.table_upcoming.rowCount()
            self.table_upcoming.insertRow(row)
            self.table_upcoming.setItem(row, 0, QTableWidgetItem(str(rid)))
            self.table_upcoming.setItem(row, 1, QTableWidgetItem(str(sale_id)))
            self.table_upcoming.setItem(row, 2, QTableWidgetItem(label))
            self.table_upcoming.setItem(row, 3, QTableWidgetItem(date_s))
            self.table_upcoming.setItem(row, 4, QTableWidgetItem(rtype))
            self.table_upcoming.setItem(row, 6, QTableWidgetItem(''))

            btn = AnimatedButton("إرسال واتساب", role="primary")

            def make_upcoming_handler(ph=phone, r_type=rtype):
                if r_type == '3days':
                    msg = f'مرحباً! نأمل أن تجربتك في مركز {clinic} كانت رائعة. يسعدنا سماع رأيك أو ملاحظاتك.'
                elif r_type == '4months':
                    msg = f'مرحباً! نود تذكيرك بزيارة مركز {clinic} لفحص نظرك أو تجديد نظارتك. نرحب بك دائماً.'
                elif r_type == 'next_exam':
                    msg = f'تذكير بموعد فحص العين القادم في مركز {clinic}. نتطلع لرؤيتك قريباً!'
                else:
                    msg = f'مرحباً! هذا تذكير من {clinic}.'
                return lambda: open_whatsapp(ph, msg)

            btn.clicked.connect(make_upcoming_handler())
            self.table_upcoming.setCellWidget(row, 5, btn)

        # --- Birthdays ---
        self.table_bdays.setRowCount(0)
        for cid, name, phone, bdate in bdays:
            row = self.table_bdays.rowCount()
            self.table_bdays.insertRow(row)
            self.table_bdays.setItem(row, 0, QTableWidgetItem(str(cid)))
            self.table_bdays.setItem(row, 1, QTableWidgetItem(name))
            self.table_bdays.setItem(row, 2, QTableWidgetItem(phone or ''))
            self.table_bdays.setItem(row, 3, QTableWidgetItem(bdate or ''))
            btn = AnimatedButton("🎉 تهنئة واتساب", role="light")
            btn.clicked.connect(lambda _, ph=phone: open_whatsapp(ph, f"🎉 عيد ميلاد سعيد! نتمنى لك يوماً رائعاً من {clinic}."))
            self.table_bdays.setCellWidget(row, 4, btn)

    # --- Reports
    def report_daily(self):
        date0 = datetime.now().strftime('%Y-%m-%d')
        conn = sqlite3.connect(DB_FILE); c = conn.cursor()
        c.execute('SELECT SUM(total), SUM(paid), SUM(remaining) FROM customers WHERE date(date)=?', (date0,))
        sums = c.fetchone(); conn.close()
        text = f"تقرير يوم {date0}:\nإجمالي المبيعات: {sums[0] or 0}\nالمدفوع: {sums[1] or 0}\nالمتبقي: {sums[2] or 0}"
        self.report_output.setPlainText(text)

    def report_monthly(self):
        month0 = datetime.now().strftime('%Y-%m')
        conn = sqlite3.connect(DB_FILE); c = conn.cursor()
        c.execute("SELECT SUM(total), SUM(paid), SUM(remaining) FROM customers WHERE strftime('%Y-%m',date)=?", (month0,))
        sums = c.fetchone(); conn.close()
        text = f"تقرير شهر {month0}:\nإجمالي المبيعات: {sums[0] or 0}\nالمدفوع: {sums[1] or 0}\nالمتبقي: {sums[2] or 0}"
        self.report_output.setPlainText(text)

    def export_sales_csv(self):
        path, _ = QFileDialog.getSaveFileName(self, 'حفظ CSV', f'msales_{datetime.now().strftime("%Y%m%d")}.csv', 'CSV Files (*.csv)')
        if not path: return
        conn = sqlite3.connect(DB_FILE); c = conn.cursor(); c.execute('SELECT id,name,age,lens_type,date,total,paid,remaining,phone FROM customers'); rows = c.fetchall(); conn.close()
        with open(path, 'w', newline='', encoding='utf-8') as f:
            w = csv.writer(f); w.writerow(['ID','name','age','lens_type','date','total','paid','remaining','phone']); w.writerows(rows)
        QMessageBox.information(self, 'تم', f'تصدير {len(rows)} صف إلى {path}')

    # --- Settings actions
    def on_quick_backup(self):
        res = backup_db_quick()
        if res:
            QMessageBox.information(self, 'تم', f'تم حفظ النسخة السريعة:\n{res}')
        else:
            QMessageBox.warning(self, 'خطأ', 'لم يتم العثور على ملف قاعدة البيانات.')

    def on_backup_saveas(self):
        dest = backup_db_saveas(self)
        if dest:
            QMessageBox.information(self, 'تم', f'تم حفظ النسخة: {dest}')

    def on_restore(self):
        ok = restore_db_from_file(self)
        if ok:
            QMessageBox.information(self, 'تم', 'تم الاستعادة. أعد تشغيل التطبيق لتطبيق التغييرات.')

    def on_logout(self):
        if QMessageBox.question(self, 'تأكيد', 'هل تريد تسجيل الخروج وإغلاق التطبيق؟') == QMessageBox.Yes:
            QApplication.quit()

    # --- Dashboard
    def update_dashboard(self):
        today = datetime.now().strftime('%Y-%m-%d')
        conn = sqlite3.connect(DB_FILE); c = conn.cursor()
        c.execute("SELECT SUM(total), COUNT(*) FROM customers WHERE date(date)=?", (today,))
        row = c.fetchone(); total = row[0] or 0; count = row[1] or 0

        c.execute("SELECT COUNT(*) FROM customers WHERE date(date)=?", (today,))
        newc = c.fetchone()[0] or 0

        # monthly total
        c.execute("SELECT SUM(total) FROM customers WHERE strftime('%Y-%m',date)=strftime('%Y-%m','now')")
        monthly_total = c.fetchone()[0] or 0

        # top lens
        c.execute("SELECT lens_type, COUNT(*) as cnt FROM customers WHERE lens_type<>'' GROUP BY lens_type ORDER BY cnt DESC LIMIT 1")
        tl = c.fetchone()
        top_lens = tl[0] if tl else "-"

        # avg sale
        c.execute("SELECT AVG(total) FROM customers")
        avg = c.fetchone()[0] or 0

        # low stock count
        c.execute("SELECT COUNT(*) FROM inventory WHERE quantity < ?", (5,))
        lowcount = c.fetchone()[0] or 0

        conn.close()

        self.card_total.value_label.setText(str(total))
        self.card_count.value_label.setText(str(count))
        self.card_new.value_label.setText(str(newc))
        self.card_monthly.value_label.setText(str(round(monthly_total, 2)))
        self.card_toplens.value_label.setText(str(top_lens))
        self.card_avgsale.value_label.setText(str(round(avg, 2)))
        self.card_lowstock.value_label.setText(str(lowcount))

        # update chart if available (monthly last 6 months)
        if CHARTS_AVAILABLE:
            self._update_monthly_chart()

    def _update_monthly_chart(self):
        # build last 6 months totals
        labels = []
        values = []
        now = datetime.now()
        conn = sqlite3.connect(DB_FILE); c = conn.cursor()
        for i in range(5, -1, -1):
            m = (now.replace(day=1) - timedelta(days=30*i)).strftime('%Y-%m')
            c.execute("SELECT SUM(total) FROM customers WHERE strftime('%Y-%m',date)=?", (m,))
            s = c.fetchone()[0] or 0
            labels.append(m)
            values.append(s)
        conn.close()

        # create chart
        series = QBarSeries()
        barset = QBarSet("المبيعات")
        for v in values:
            barset << v
        series.append(barset)
        chart = QChart()
        chart.addSeries(series)
        chart.setTitle("مبيعات الأشهر الأخيرة")
        axis = QBarCategoryAxis()
        axis.append(labels)

        chart.createDefaultAxes()
        chart.addAxis(axis, Qt.AlignBottom)
        series.attachAxis(axis)

        self.chart_view.setChart(chart)


    # --- Auto backup at close (keep last 10 autos)
    def closeEvent(self, event):
        try:
            src = Path(DB_FILE)
            if src.exists():
                backup_dir = Path('backups'); backup_dir.mkdir(exist_ok=True)
                dest = backup_dir / f"auto_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
                shutil.copy2(src, dest)
                autos = sorted(backup_dir.glob("auto_backup_*.db"), key=os.path.getmtime, reverse=True)
                for old in autos[10:]:
                    try: old.unlink()
                    except: pass
        except Exception as e:
            print("Error auto-backup:", e)
        super().closeEvent(event)

    # --- Filters
    def apply_filters(self):
        from_date = self.filter_from.date().toString("yyyy-MM-dd")
        to_date = self.filter_to.date().toString("yyyy-MM-dd")
        lens = self.filter_lens.currentText()
        payment = self.filter_payment.currentText()

        query = "SELECT id,name,age,lens_type,date,total,paid,remaining,phone FROM customers WHERE date(date) BETWEEN ? AND ?"
        params = [from_date + " 00:00:00", to_date + " 23:59:59"]

        if lens and lens != "الكل":
            query += " AND lens_type=?"
            params.append(lens)
        if payment == "مدفوع بالكامل":
            query += " AND remaining=0"
        elif payment == "باقي عليه":
            query += " AND remaining>0"

        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute(query, params)
        rows = c.fetchall()
        conn.close()

        self.table_sales.setRowCount(0)
        for r in rows:
            row = self.table_sales.rowCount(); self.table_sales.insertRow(row)
            for i, val in enumerate(r):
                self.table_sales.setItem(row, i, QTableWidgetItem(str(val)))

# ---------------- Login dialog ----------------
class LoginDialog(QDialog):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("تسجيل الدخول - " + APP_NAME)
        self.setFixedSize(480,360)
        self.setLayoutDirection(Qt.RightToLeft)
        self.build()

    def build(self):
        v = QVBoxLayout()
        logo_path = Path(LOGO_FILE)
        if logo_path.exists():
            pix = QPixmap(str(logo_path))
            lbl = QLabel()
            pix = pix.scaledToWidth(220, Qt.SmoothTransformation)
            lbl.setPixmap(pix)
            lbl.setAlignment(Qt.AlignCenter)
            v.addWidget(lbl)
        else:
            label = QLabel(APP_NAME); label.setStyleSheet("font-size:16pt; font-weight:bold;"); label.setAlignment(Qt.AlignCenter)
            v.addWidget(label)

        subtitle = QLabel("نظام إدارة مركز النظارات")
        subtitle.setAlignment(Qt.AlignCenter)
        subtitle.setStyleSheet("color:#475569; font-size:10pt;")
        v.addWidget(subtitle)

        v.addSpacing(8)
        self.user = QLineEdit(); self.user.setPlaceholderText("اسم المستخدم")
        self.passw = QLineEdit(); self.passw.setPlaceholderText("كلمة المرور"); self.passw.setEchoMode(QLineEdit.Password)
        v.addWidget(self.user); v.addWidget(self.passw)
        h = QHBoxLayout()
        self.btn_login = AnimatedButton("دخول", role="primary"); self.btn_login.clicked.connect(self.try_login)
        self.btn_register = AnimatedButton("تسجيل مستخدم جديد", role="muted"); self.btn_register.clicked.connect(self.register_user)
        h.addWidget(self.btn_register); h.addWidget(self.btn_login)
        v.addLayout(h)
        self.setLayout(v)

    def try_login(self):
        u = self.user.text().strip(); p = self.passw.text().strip()
        conn = sqlite3.connect(DB_FILE); c = conn.cursor()
        c.execute('SELECT password FROM users WHERE username=?', (u,))
        row = c.fetchone(); conn.close()
        if row and row[0] == p:
            self.accept(); self.username = u
        else:
            QMessageBox.warning(self, 'فشل', 'اسم المستخدم أو كلمة المرور غير صحيحة')

    def register_user(self):
        u = self.user.text().strip(); p = self.passw.text().strip()
        if not u or not p:
            QMessageBox.warning(self, 'تنبيه', 'ادخل اسم مستخدم وكلمة مرور للتسجيل'); return
        conn = sqlite3.connect(DB_FILE); c = conn.cursor()
        try:
            c.execute('INSERT INTO users (username,password) VALUES (?,?)', (u,p)); conn.commit(); conn.close()
            QMessageBox.information(self, 'تم', 'تم إنشاء مستخدم جديد')
        except sqlite3.IntegrityError:
            conn.close(); QMessageBox.warning(self, 'خطأ', 'اسم المستخدم موجود بالفعل')

# ---------------- Run ----------------
def main():
    init_db()
    app = QApplication(sys.argv)
    app.setFont(QFont("Cairo", 10, QFont.DemiBold))
    dlg = LoginDialog()
    if dlg.exec() == QDialog.Accepted:
        w = MainWindow(dlg.username)
        w.show()
        sys.exit(app.exec())

if __name__ == "__main__":
    main()
