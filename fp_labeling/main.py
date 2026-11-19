"""Tkinter entry point for Labelme review extraction."""
import csv
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

if __package__:
    from .extraction import extract
else:
    from extraction import extract  # Direct execution and PyInstaller.


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


def main():
    window = tk.Tk()
    ReviewFilterApp(window)
    window.mainloop()


if __name__ == "__main__":
    main()
