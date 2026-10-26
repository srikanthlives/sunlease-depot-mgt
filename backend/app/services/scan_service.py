"""Reading filled-in paper trip sheets back off a scan, offline.

The printed sheet (frontend/src/pages/PrintTripSheet.jsx) puts every handwritten value in its own
box, so the hard part of OCR - deciding where a character starts and ends - is already solved on
paper. This module therefore does not try to understand the form: it finds the boxes, reads one
character from each, and maps the box rows onto the runs of the schedule version the page names in
its printed ID line. Nothing about a particular schedule is hardcoded, so any sheet this app prints
can be read, however many runs or pages it has.

    pages = rasterise(pdf_bytes)              # 200 dpi grayscale
    for img in pages:
        img = deskew(img)
        cells = find_cells(img)               # every box on the page, in reading order
        ident = read_id_line(img, cells)      # schedule / version / date off the printed line

Anything the reader is not sure about is left empty and reported as an issue naming that one field,
for a clerk to key in on the trip sheet screen. A page is never guessed at: a field is either read
with confidence or flagged.
"""
from __future__ import annotations

import datetime as dt
import io
import os
import re
from dataclasses import dataclass, field

import cv2
import numpy as np
import pypdfium2 as pdfium
import pytesseract

DPI = 200
MM = DPI / 25.4                      # pixels per mm at DPI
BOX_W, BOX_H = 4.2 * MM, 5.5 * MM    # character box on paper
TICK = 3.8 * MM                      # tick box (Ran / Cut / Not)
SIZE_TOL = 0.30                      # how far a cell may differ from the nominal size
MIN_CONF = 55                        # tesseract confidence below which a field is "unsure"
INK = 0.14                           # ink coverage that counts as a tick


# --------------------------------------------------------------------------
# Image preparation
# --------------------------------------------------------------------------
def rasterise(pdf_bytes: bytes, dpi: int = DPI) -> list[np.ndarray]:
    """Every page of the PDF as a grayscale array. Raises ValueError if it is not a readable PDF."""
    try:
        doc = pdfium.PdfDocument(io.BytesIO(pdf_bytes))
        out = []
        for i in range(len(doc)):
            pil = doc[i].render(scale=dpi / 72).to_pil().convert("L")
            out.append(np.asarray(pil))
        return out
    except Exception as e:                                   # noqa: BLE001 - any parse failure is the same to us
        raise ValueError(f"could not read the PDF: {e}") from e


def binarise(img: np.ndarray) -> np.ndarray:
    """Ink as white on black, tolerant of uneven scanner lighting."""
    return cv2.adaptiveThreshold(img, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 35, 11)


def deskew(img: np.ndarray) -> np.ndarray:
    """Straighten the page using the long horizontal rules of the tables (usually a fraction of a degree)."""
    bw = binarise(img)
    horizontal = cv2.morphologyEx(bw, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (int(40 * MM), 1)))
    lines = cv2.HoughLinesP(horizontal, 1, np.pi / 720, threshold=200,
                            minLineLength=int(60 * MM), maxLineGap=int(2 * MM))
    if lines is None:
        return img
    angles = [np.degrees(np.arctan2(y2 - y1, x2 - x1)) for x1, y1, x2, y2 in lines[:, 0]]
    angles = [a for a in angles if abs(a) < 8]
    if not angles:
        return img
    angle = float(np.median(angles))
    if abs(angle) < 0.08:
        return img
    h, w = img.shape
    m = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
    return cv2.warpAffine(img, m, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE,
                          borderValue=255)


# --------------------------------------------------------------------------
# Finding the boxes
# --------------------------------------------------------------------------
@dataclass
class Cell:
    x: int
    y: int
    w: int
    h: int

    @property
    def cx(self) -> float:
        return self.x + self.w / 2

    @property
    def cy(self) -> float:
        return self.y + self.h / 2

    def crop(self, img: np.ndarray, pad: int = 2) -> np.ndarray:
        """The inside of the box, without its printed border."""
        b = max(2, int(0.35 * MM)) + pad
        return img[self.y + b:self.y + self.h - b, self.x + b:self.x + self.w - b]


def find_cells(img: np.ndarray) -> list[Cell]:
    """Every character box and tick box on the page, as rectangles.

    Boxes are drawn as a grid of printed lines, so the cells are found the way table cells usually
    are: isolate the long horizontal and vertical strokes, intersect them, and keep the enclosed
    rectangles whose size matches a box on paper.
    """
    bw = binarise(img)
    hor = cv2.morphologyEx(bw, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (int(2.6 * MM), 1)))
    ver = cv2.morphologyEx(bw, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (1, int(2.6 * MM))))
    grid = cv2.dilate(cv2.bitwise_or(hor, ver), np.ones((3, 3), np.uint8), iterations=1)
    # the cells are the holes in the grid
    contours, _ = cv2.findContours(cv2.bitwise_not(grid), cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    cells = []
    for c in contours:
        x, y, w, h = cv2.boundingRect(c)
        if _is_box(w, h, BOX_W, BOX_H) or _is_box(w, h, TICK, TICK):
            cells.append(Cell(x, y, w, h))
    return _dedupe(cells)


def _dedupe(cells: list[Cell]) -> list[Cell]:
    """A printed border can yield both its outer and its inner outline; keep the outer one."""
    out: list[Cell] = []
    for c in sorted(cells, key=lambda c: -c.w * c.h):
        if not any(abs(c.cx - k.cx) < 0.3 * k.w and abs(c.cy - k.cy) < 0.3 * k.h for k in out):
            out.append(c)
    return out


def _is_box(w: int, h: int, nw: float, nh: float) -> bool:
    return abs(w - nw) <= SIZE_TOL * nw and abs(h - nh) <= SIZE_TOL * nh


def rows_of(cells: list[Cell]) -> list[list[Cell]]:
    """Group the boxes into printed rows (one row of boxes belongs to one run), top to bottom."""
    out: list[list[Cell]] = []
    for c in sorted(cells, key=lambda c: c.cy):
        if out and abs(c.cy - np.median([x.cy for x in out[-1]])) < 0.55 * BOX_H:
            out[-1].append(c)
        else:
            out.append([c])
    for r in out:
        r.sort(key=lambda c: c.x)
    return [r for r in out if len(r) >= 3]


# --------------------------------------------------------------------------
# Reading characters
# --------------------------------------------------------------------------
def _strip(img: np.ndarray, cells: list[Cell], pad: int = 6) -> np.ndarray:
    """The boxes of one field side by side on white, so tesseract reads them as a single word."""
    crops = [c.crop(img) for c in cells]
    crops = [c for c in crops if c.size]
    if not crops:
        return np.full((10, 10), 255, np.uint8)
    h = max(c.shape[0] for c in crops)
    parts = []
    for c in crops:
        top = (h - c.shape[0]) // 2
        canvas = np.full((h, c.shape[1]), 255, np.uint8)
        canvas[top:top + c.shape[0], :] = c
        parts.append(canvas)
        parts.append(np.full((h, pad), 255, np.uint8))
    strip = np.hstack(parts)
    # tesseract wants characters around 30-60 px tall and clean black on white; a 200 dpi box is
    # smaller than that, so the strip is enlarged and thresholded before it is read
    scale = max(1.0, 56 / strip.shape[0])
    if scale > 1.01:
        strip = cv2.resize(strip, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    strip = cv2.threshold(strip, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
    return cv2.copyMakeBorder(strip, 20, 20, 20, 20, cv2.BORDER_CONSTANT, value=255)


# A single digit is read with a wider alphabet and mapped back, because tesseract often prefers the
# letter that a hand-drawn digit resembles. Everything here is a shape confusion, not a guess at
# what the value ought to be.
AS_DIGIT = {"O": "0", "o": "0", "Q": "0", "D": "0", "\u00d8": "0", "\u00f8": "0", "()": "0",
            "l": "1", "I": "1", "|": "1", "i": "1", "/": "1", "\\": "1",
            "S": "5", "s": "5", "B": "8", "Z": "2", "z": "2", "G": "6", "T": "7", "A": "4", "q": "9", "g": "9"}


def read_field(img: np.ndarray, cells: list[Cell]) -> tuple[str, float]:
    """One field's characters and the confidence tesseract reports (0-100).

    No character whitelist: tesseract's LSTM engine ignores `tessedit_char_whitelist` and answers
    with nothing at all when it is set, so the reading is narrowed to digits afterwards instead,
    through AS_DIGIT.
    """
    if not cells:
        return "", 0.0
    strip = _strip(img, cells)
    # psm 10 reads a lone character; psm 7 reads a line of them
    cfg = f"--psm {10 if len(cells) == 1 else 7} --oem 1"
    try:
        data = pytesseract.image_to_data(strip, config=cfg, output_type=pytesseract.Output.DICT)
    except Exception:                                        # noqa: BLE001 - tesseract missing or unhappy
        return "", 0.0
    words, confs = [], []
    for text, conf in zip(data.get("text", []), data.get("conf", [])):
        text = (text or "").strip()
        if text and float(conf) >= 0:
            words.append(text)
            confs.append(float(conf))
    out = "".join(words)
    return out, (min(confs) if confs else 0.0)


def _digit_in(img: np.ndarray, cell: Cell) -> tuple[str | None, float]:
    """The one digit in a box, or None when the box holds something that cannot be read as a digit."""
    text, conf = read_field(img, [cell])
    for ch in text.strip():
        d = AS_DIGIT.get(ch, ch)
        if d.isdigit():
            return d, conf
    return None, conf


def written(img: np.ndarray, cells: list[Cell]) -> list[bool]:
    """Which boxes of a field have anything in them. Ink tells a blank box from a written one far
    more reliably than OCR does, and it keeps blank fields from being reported as unreadable."""
    return [ink_ratio(img, c) >= 0.03 for c in cells]


def read_digits(img: np.ndarray, cells: list[Cell]) -> tuple[str | None, float]:
    """The digits a field holds.

    Returns ("", 100) for a field nobody wrote in, the digits when they are read with confidence, and
    None when there is something in the boxes that cannot be made out - which is what becomes a
    warning pointing at this one field.
    """
    if not cells:
        return "", 100.0
    ink = written(img, cells)
    if not any(ink):
        return "", 100.0
    # the whole field in one call: right most of the time, and one call instead of several
    text, conf = read_field(img, cells)
    text = re.sub(r"\D", "", "".join(AS_DIGIT.get(ch, ch) for ch in text))
    if len(text) == sum(ink) and conf >= MIN_CONF and all(ink[len(cells) - sum(ink):]):
        return text.rjust(len(cells), "0") if sum(ink) < len(cells) else text, conf
    # box by box, which copes with a stray mark joining two boxes or a lone digit
    chars, cs = [], []
    for c, has in zip(cells, ink):
        if not has:
            chars.append("0")           # an unwritten leading box reads as a zero
            continue
        d, cf = _digit_in(img, c)
        if d is None:
            return None, cf
        chars.append(d)
        cs.append(cf)
    return "".join(chars), (min(cs) if cs else 0.0)


def ink_ratio(img: np.ndarray, cell: Cell) -> float:
    """How much of a box is filled - how a tick is told from an empty box."""
    crop = cell.crop(img, pad=4)
    if not crop.size:
        return 0.0
    return float((crop < 160).mean())


def ticked(img: np.ndarray, cells: list[Cell]) -> int | None:
    """Which of the tick boxes was marked, or None when none or several were."""
    ratios = [ink_ratio(img, c) for c in cells]
    marked = [i for i, r in enumerate(ratios) if r >= INK]
    return marked[0] if len(marked) == 1 else None


# --------------------------------------------------------------------------
# Identifying the page
# --------------------------------------------------------------------------
@dataclass
class PageId:
    schedule_id: int | None = None
    version_number: int | None = None
    date: dt.date | None = None
    fleet_number: str | None = None
    raw: str = ""
    y: int = 0            # where the ID line sits: the run table starts below it


ID_RE = re.compile(r"DEPOT\W*TS\s*S\s*(\d+)\s*V\s*(\d+)\s*(\d{8})?", re.I)


def read_id_line(img: np.ndarray, cells: list[Cell] | None = None) -> PageId:
    """The printed `DEPOT-TS S<schedule> V<version> <yyyymmdd>` line, which repeats on every page.

    It is printed small, in the head of the run table, so the whole page is read and the line picked
    out by its shape. That costs one tesseract call but needs no knowledge of where it sits.
    """
    text = ""
    for attempt in (img, cv2.resize(img, None, fx=1.5, fy=1.5, interpolation=cv2.INTER_CUBIC)):
        try:
            text = pytesseract.image_to_string(attempt, config="--psm 6 --oem 1")
        except Exception:                                    # noqa: BLE001
            text = ""
        if ID_RE.search(text.replace("\u00b7", " ")):
            break
    m = ID_RE.search(text.replace("·", " "))
    out = PageId(raw=text.strip()[:400], y=_id_line_y(img))
    if not m:
        return out
    out.schedule_id, out.version_number = int(m.group(1)), int(m.group(2))
    if m.group(3):
        try:
            out.date = dt.datetime.strptime(m.group(3), "%Y%m%d").date()
        except ValueError:
            pass
    return out


def _gap_pattern(row: list[Cell]) -> list[int]:
    """Sizes of the printed groups in a row: boxes of one group touch, groups are separated by a gap."""
    groups, run = [], 1
    for a, b in zip(row, row[1:]):
        if b.x - (a.x + a.w) > 0.3 * BOX_W:
            groups.append(run)
            run = 1
        else:
            run += 1
    groups.append(run)
    return groups


def _id_line_y(img: np.ndarray) -> int:
    """Bottom of the printed ID line. It heads the run table, so the run rows are below it."""
    try:
        d = pytesseract.image_to_data(img, config="--psm 6 --oem 1", output_type=pytesseract.Output.DICT)
    except Exception:                                        # noqa: BLE001
        return 0
    for text, top, height in zip(d.get("text", []), d.get("top", []), d.get("height", [])):
        if text and text.upper().startswith("DEPOT-TS"):
            return int(top) + int(height)
    return 0


def read_hand_date(img: np.ndarray, cells: list[Cell]) -> dt.date | None:
    """An undated sheet carries DD/MM/YYYY boxes; they are the 8 boxes printed as 2 / 2 / 4."""
    combs = [r for r in rows_of(cells) if len(r) == 8 and _gap_pattern(r) == [2, 2, 4]]
    if not combs:
        return None
    text, conf = read_digits(img, combs[0])
    if not text or conf < MIN_CONF:
        return None
    try:
        return dt.datetime.strptime(text, "%d%m%Y").date()
    except ValueError:
        return None


# --------------------------------------------------------------------------
# Reading one run's row of boxes
# --------------------------------------------------------------------------
# Fields in printed order. The printed sheet varies the row by what the run is: a charging row has
# no odometer boxes, and a run that is not a passenger trip prints no "Cut" tick and no stop box
# (it cannot be cut short at a stop). The caller passes what the run is, so nothing is guessed.
def fields_for(is_trip: bool, is_charging: bool) -> list[tuple[str, int]]:
    f = [("status", 3 if is_trip else 2), ("departed", 4), ("arrived", 4), ("arrived_day", 1)]
    if not is_charging:
        f += [("odo_start", 6), ("odo_end", 6)]
    f += [("start_soc", 3), ("end_soc", 3), ("reason", 3)]
    if is_trip:
        f += [("stop", 2)]
    return f


@dataclass
class RowRead:
    values: dict = field(default_factory=dict)
    issues: list[dict] = field(default_factory=list)
    read: int = 0
    unsure: int = 0


def _slice(cells: list[Cell], fields: list[tuple[str, int]]) -> dict[str, list[Cell]] | None:
    if sum(c for _, c in fields) != len(cells):
        return None
    out, i = {}, 0
    for name, count in fields:
        out[name] = cells[i:i + count]
        i += count
    return out


def read_row(img: np.ndarray, cells: list[Cell], label: str, is_trip: bool, is_charging: bool) -> RowRead:
    """Read one run's row of boxes, left to right, against the layout that run was printed with."""
    r = RowRead()
    fields = fields_for(is_trip, is_charging)
    groups = _slice(cells, fields)
    if groups is None:
        r.issues.append({"field": None, "run": label, "severity": "WARNING", "code": "ROW_NOT_READ",
                         "message": f"{label}: the boxes on this line could not be made out "
                                    f"({len(cells)} found, {sum(c for _, c in fields)} expected) - "
                                    f"enter this run by hand"})
        r.unsure += 1
        return r

    def digits(name: str, out_key: str):
        text, conf = read_digits(img, groups[name])
        if text is None:
            r.unsure += 1
            r.issues.append({"field": out_key, "run": label, "severity": "WARNING", "code": "FIELD_UNSURE",
                             "message": f"{label}: {name.replace('_', ' ')} could not be read - enter it by hand"})
            return None
        r.read += 1
        return text

    mark = ticked(img, groups["status"])
    if mark is None:
        r.issues.append({"field": "status", "run": label, "severity": "WARNING", "code": "STATUS_UNSURE",
                         "message": f"{label}: no single tick in the status boxes - set the status by hand"})
        r.unsure += 1
    else:
        r.read += 1
        statuses = ["OPERATED", "PARTIAL", "CANCELLED"] if is_trip else ["OPERATED", "CANCELLED"]
        r.values["status"] = statuses[mark]

    dep, arr = digits("departed", "actual_start_time"), digits("arrived", "actual_end_time")
    day = digits("arrived_day", "actual_end_day_offset")
    for key, text in (("actual_start_time", dep), ("actual_end_time", arr)):
        if text and _valid_time(text):
            r.values[key] = f"{text[:2]}:{text[2:]}"
        elif text:
            r.issues.append({"field": key, "run": label, "severity": "WARNING", "code": "FIELD_INVALID",
                             "message": f"{label}: {text} is not a time - enter it by hand"})
            r.unsure += 1
    if day in ("0", "1"):
        r.values["actual_end_day_offset"] = int(day)
    elif day == "":
        # the box was left blank. Harmless when the arrival is later in the clock than the departure
        # (it can only be the same day); worth a warning when the run looks like it crossed midnight
        crossed = (r.values.get("actual_start_time") or "") > (r.values.get("actual_end_time") or "")
        if crossed:
            r.issues.append({"field": "actual_end_day_offset", "run": label, "severity": "WARNING",
                             "code": "DAY_BLANK",
                             "message": f"{label}: the arrival looks earlier than the departure but the +day box is "
                                        f"empty - say whether it arrived after midnight"})
            r.unsure += 1
        else:
            r.values["actual_end_day_offset"] = 0
    for name, key in (("odo_start", "start_odometer_km"), ("odo_end", "end_odometer_km")):
        if name not in groups:
            continue
        text = digits(name, key)
        if text:
            r.values[key] = float(int(text))
    for name, key in (("start_soc", "start_soc_pct"), ("end_soc", "end_soc_pct")):
        text = digits(name, key)
        if text is not None and text.strip():
            v = int(text)
            if v <= 100:
                r.values[key] = v
    for name, key in (("reason", "reason_id"), ("stop", "stop_sequence")):
        if name not in groups:
            continue
        text, conf = read_digits(img, groups[name])
        if text and text.strip("0"):          # all zeros means the box was left blank
            r.values[key] = int(text)
    return r


def _valid_time(text: str) -> bool:
    return len(text) == 4 and int(text[:2]) < 24 and int(text[2:]) < 60


# --------------------------------------------------------------------------
# Where page images are kept
# --------------------------------------------------------------------------
def scan_dir(scan_id: int) -> str:
    base = os.environ.get("DEPOT_SCAN_DIR") or ("/data/scans" if os.path.isdir("/data") else
                                                os.path.join(os.path.dirname(__file__), "../../../data/scans"))
    path = os.path.abspath(os.path.join(base, str(scan_id)))
    os.makedirs(path, exist_ok=True)
    return path


def save_page(scan_id: int, page_no: int, img: np.ndarray) -> str:
    """Keep the straightened page, so a clerk can compare it with what was read."""
    path = os.path.join(scan_dir(scan_id), f"page-{page_no}.png")
    cv2.imwrite(path, img, [cv2.IMWRITE_PNG_COMPRESSION, 6])
    return path


def tesseract_available() -> bool:
    try:
        pytesseract.get_tesseract_version()
        return True
    except Exception:                                        # noqa: BLE001
        return False
