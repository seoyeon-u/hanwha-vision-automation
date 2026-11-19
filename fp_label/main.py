import csv
import json
import os
import queue
import shutil
import threading
import tkinter as tk
from collections import Counter
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText
from uuid import uuid4


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff"}
EXTENSIONS = IMAGE_EXTENSIONS | {".json"}
CSV_COLUMNS = (
    "image_filename", "json_filename", "object_count", "status", "reason",
    "output_path",
)


def collect_files(input_text, groups, report):
    seen = set()

    def add(path):
        if path.suffix.lower() not in EXTENSIONS:
            return
        resolved = path.resolve()
        identity = os.path.normcase(str(resolved))
        if identity in seen:
            return
        seen.add(identity)
        key = (os.path.normcase(str(path.parent.resolve())), path.stem.casefold())
        kind = "json" if path.suffix.lower() == ".json" else "image"
        groups.setdefault(key, {"image": [], "json": []})[kind].append(path)

    for line in input_text.splitlines():
        value = line.strip().strip('"')
        if not value:
            continue
        try:
            path = Path(value).absolute()
            if path.is_dir():
                # Scan only this folder so previous output subfolders stay out.
                for child in sorted(path.iterdir()):
                    try:
                        if child.is_file():
                            add(child)
                    except (OSError, ValueError, RuntimeError) as exc:
                        report(child, f"파일 접근 실패 ({exc})")
            elif not path.is_file():
                report(path, "경로가 없거나 파일에 접근할 수 없습니다.")
            elif path.suffix.lower() not in EXTENSIONS:
                report(path, "지원하지 않는 확장자입니다.")
            else:
                add(path)
        except (OSError, ValueError, RuntimeError) as exc:
            report(value, f"경로 처리 실패 ({exc})")


def copy_pair(image, annotation, output):
    """Reserve both names exclusively before copying either source."""
    reserved = []
    try:
        for source in (image, annotation):
            target = output / source.name
            with target.open("xb"):
                reserved.append(target)
        for source, target in zip((image, annotation), reserved):
            shutil.copy2(source, target)
    except OSError as exc:
        cleanup_errors = []
        for target in reversed(reserved):
            try:
                target.unlink()
            except PermissionError:
                # On Windows copy2 may have copied a read-only attribute.
                try:
                    target.chmod(0o600)
                    target.unlink()
                except OSError as cleanup_exc:
                    cleanup_errors.append(str(cleanup_exc))
            except OSError as cleanup_exc:
                cleanup_errors.append(str(cleanup_exc))
        reason = f"출력 파일명 충돌 ({exc.filename})" if isinstance(
            exc, FileExistsError
        ) else f"복사 실패 ({exc})"
        if cleanup_errors:
            reason += " / 생성 파일 정리 실패 (" + ", ".join(cleanup_errors) + ")"
        return False, isinstance(exc, FileExistsError), reason
    return True, False, ""


def extract(input_text, output, notify):
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    stats = Counter()
    groups = {}
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = output / f"처리내역_{stamp}_{uuid4().hex[:8]}.csv"
    with log_path.open("x", encoding="utf-8-sig", newline="") as log:
        writer = csv.writer(log)
        writer.writerow(CSV_COLUMNS)

        def report(path, reason):
            stats["input_warnings"] += 1
            name = Path(path).name
            suffix = Path(path).suffix.lower()
            writer.writerow((
                name if suffix in IMAGE_EXTENSIONS else "",
                name if suffix == ".json" else "",
                "", "error", f"{path} — {reason}", "",
            ))
            notify("message", f"[경고] {path} — {reason}")

        notify("message", "입력 경로를 검색하고 있습니다.")
        collect_files(input_text, groups, report)
        total = len(groups)
        notify("progress", (0, total))
        for index, group in enumerate(groups.values(), 1):
            images, annotations = group["image"], group["json"]
            image_names = " / ".join(path.name for path in images)
            json_names = " / ".join(path.name for path in annotations)
            paths = images + annotations
            count, status, reason, destination = "", "error", "", ""
            level = "오류"
            if not images or not annotations:
                stats["missing"] += 1
                reason = "대응 이미지 누락" if not images else "대응 JSON 누락"
                level = "경고"
            elif len(images) != 1 or len(annotations) != 1:
                stats["collisions"] += 1
                reason = "같은 폴더에서 기본 이름이 같은 이미지 또는 JSON이 여러 개입니다."
                level = "경고"
            else:
                stats["pairs"] += 1
                image, annotation = images[0], annotations[0]
                try:
                    with annotation.open(encoding="utf-8-sig") as source:
                        data = json.load(source)
                    if not isinstance(data, dict):
                        raise ValueError("JSON 최상위 값이 객체가 아닙니다.")
                    if "shapes" not in data:
                        raise KeyError("shapes")
                    shapes = data["shapes"]
                    if not isinstance(shapes, list):
                        raise ValueError("shapes 값이 배열이 아닙니다.")
                except KeyError:
                    stats["missing_shapes"] += 1
                    reason = "shapes 키가 없습니다."
                    level = "경고"
                except (OSError, ValueError, RecursionError) as exc:
                    stats["json_errors"] += 1
                    reason = f"JSON 읽기 또는 형식 오류 ({exc})"
                else:
                    count = len(shapes)
                    if count == 0:
                        stats["empty"] += 1
                        status, reason = "excluded", "shapes 배열이 비어 있습니다."
                    else:
                        stats["with_objects"] += 1
                        copied, collision, reason = copy_pair(image, annotation, output)
                        if copied:
                            stats["copied"] += 1
                            status, destination = "copied", str(output)
                        elif collision:
                            stats["collisions"] += 1
                            level = "경고"
                        else:
                            stats["copy_errors"] += 1
            if status == "error":
                sources = " / ".join(str(path) for path in paths)
                notify("message", f"[{level}] {sources} — {reason}")
                reason = f"{reason} / 입력: {sources}"
            writer.writerow((image_names, json_names, count, status, reason, destination))
            notify("progress", (index, total))
    return stats, output, log_path


class ReviewFilterApp:
    def __init__(self, root):
        self.root = root
        self.events = queue.Queue()
        self.running = False
        root.title("Labelme 검수 대상 추출")
        root.geometry("820x750")
        root.minsize(620, 580)
        root.protocol("WM_DELETE_WINDOW", self.close)
        frame = ttk.Frame(root, padding=14)
        frame.pack(fill="both", expand=True)

        ttk.Label(frame, text="파일 탐색기에서 복사한 파일 또는 폴더 경로를 붙여넣으세요.").pack(anchor="w")
        self.inputs = ScrolledText(frame, height=7, undo=True, wrap="none")
        self.inputs.pack(fill="x", pady=(5, 6))
        self.input_button = ttk.Button(frame, text="입력 폴더 선택", command=self.select_input)
        self.input_button.pack(anchor="w")
        output_row = ttk.Frame(frame)
        output_row.pack(fill="x", pady=10)
        self.output = tk.StringVar()
        self.output_entry = ttk.Entry(output_row, textvariable=self.output)
        self.output_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.output_button = ttk.Button(output_row, text="출력 폴더 선택", command=self.select_output)
        self.output_button.pack(side="right")
        self.start_button = ttk.Button(frame, text="객체 있는 파일만 추출", command=self.start)
        self.start_button.pack(anchor="w")
        self.progress = ttk.Progressbar(frame, mode="determinate")
        self.progress.pack(fill="x", pady=(8, 2))
        self.progress_text = tk.StringVar(value="대기 중")
        ttk.Label(frame, textvariable=self.progress_text).pack(anchor="w")
        ttk.Label(frame, text="처리 결과와 오류 및 경고").pack(anchor="w", pady=(8, 4))
        self.results = ScrolledText(frame, height=12, state="disabled", wrap="word")
        self.results.pack(fill="both", expand=True)
        self.root.after(75, self.poll)

    def select_input(self):
        folder = filedialog.askdirectory(parent=self.root, title="입력 폴더 선택")
        if folder:
            if self.inputs.get("1.0", "end-1c").strip():
                self.inputs.insert("end", "\n")
            self.inputs.insert("end", f'"{folder}"')

    def select_output(self):
        folder = filedialog.askdirectory(parent=self.root, title="출력 폴더 선택")
        if folder:
            self.output.set(folder)

    def controls(self, enabled):
        self.running = not enabled
        state = "normal" if enabled else "disabled"
        for widget in (self.inputs, self.input_button, self.output_button,
                       self.output_entry, self.start_button):
            widget.configure(state=state)

    def close(self):
        if self.running:
            messagebox.showinfo("처리 중", "복사와 기록 저장이 끝난 후 닫을 수 있습니다.", parent=self.root)
        else:
            self.root.destroy()

    def start(self):
        inputs = self.inputs.get("1.0", "end-1c")
        output = self.output.get().strip().strip('"')
        if not inputs.strip() or not output:
            messagebox.showwarning("입력 확인", "입력 경로와 출력 폴더를 지정하세요.", parent=self.root)
            return
        self.controls(False)
        self.progress.configure(value=0)
        self.progress_text.set("입력 검색 중")
        self.results.configure(state="normal")
        self.results.delete("1.0", "end")
        self.results.configure(state="disabled")
        threading.Thread(target=self.run, args=(inputs, Path(output)), daemon=True).start()

    def run(self, inputs, output):
        def notify(kind, value):
            self.events.put((kind, value))

        try:
            result = extract(inputs, output, notify)
        except (OSError, ValueError, RuntimeError, csv.Error) as exc:
            notify("failed", str(exc))
        else:
            notify("done", result)

    def append(self, message):
        self.results.configure(state="normal")
        self.results.insert("end", message + "\n")
        self.results.see("end")
        self.results.configure(state="disabled")

    def poll(self):
        # Limit work per callback so large batches leave the GUI responsive.
        for _ in range(150):
            try:
                kind, value = self.events.get_nowait()
            except queue.Empty:
                break
            if kind == "progress":
                current, total = value
                self.progress.configure(maximum=max(total, 1), value=current)
                self.progress_text.set(f"처리 {current:,} / {total:,}")
            elif kind == "message":
                self.append(value)
            elif kind == "failed":
                self.append(f"[오류] 작업 중단 — {value}")
                self.progress_text.set("작업 중단")
                self.controls(True)
            elif kind == "done":
                stats, output, log_path = value
                copied = stats["copied"]
                self.append(
                    f"\n[처리 결과]\n"
                    f"전체 이미지-JSON 쌍: {stats['pairs']:,}쌍\n"
                    f"객체 정보 있음: {stats['with_objects']:,}쌍\n"
                    f"객체 정보 없음: {stats['empty']:,}쌍\n"
                    f"복사 완료: {copied:,}쌍\n"
                    f"복사된 이미지: {copied:,}개\n"
                    f"복사된 JSON: {copied:,}개\n"
                    f"누락된 파일: {stats['missing']:,}개\n"
                    f"JSON 오류: {stats['json_errors']:,}개\n"
                    f"shapes 키 누락: {stats['missing_shapes']:,}개\n"
                    f"파일명 충돌: {stats['collisions']:,}건\n"
                    f"입력 경고: {stats['input_warnings']:,}건\n"
                    f"복사 오류: {stats['copy_errors']:,}건\n"
                    f"저장 위치: {output}\n"
                    f"CSV 처리 내역: {log_path}"
                )
                self.progress_text.set("처리 완료")
                self.controls(True)
        self.root.after(75, self.poll)


if __name__ == "__main__":
    window = tk.Tk()
    ReviewFilterApp(window)
    window.mainloop()
