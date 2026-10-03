"""Online-only clickable text and noninteractive native map snapshots."""
import io
import queue
import tkinter as tk
import webbrowser
from urllib.parse import urlencode
from PIL import Image, ImageTk
from online_chat.message_content import URL_PATTERN
from .shared import THEME, ui_font, bind_click


def map_url(location, provider="yandex"):
    lat, lon = location["latitude"], location["longitude"]
    if provider == "2gis": return f"https://2gis.ru/geo/{lon:.6f},{lat:.6f}"
    return "https://yandex.ru/maps/?" + urlencode({"ll": f"{lon:.6f},{lat:.6f}", "pt": f"{lon:.6f},{lat:.6f}", "z": "16"})


class LinkedMessageText(tk.Text):
    def __init__(self, master, text, bg, fg):
        super().__init__(master, width=40, height=1, wrap="word", bg=bg, fg=fg,
                         font=ui_font(13), relief="flat", bd=0, highlightthickness=0,
                         padx=14, pady=10, cursor="arrow", exportselection=False)
        self.insert("1.0", text)
        for index, match in enumerate(URL_PATTERN.finditer(text)):
            value = match.group().rstrip(".,!?;:)]}")
            url = "https://" + value if value.lower().startswith("www.") else value
            tag = "link" + str(index)
            self.tag_add(tag, f"1.0+{match.start()}c", f"1.0+{match.start() + len(value)}c")
            self.tag_configure(tag, underline=True)
            self.tag_bind(tag, "<Button-1>", lambda event, target=url: webbrowser.open(target))
            self.tag_bind(tag, "<Enter>", lambda event: self.configure(cursor="hand2"))
            self.tag_bind(tag, "<Leave>", lambda event: self.configure(cursor="arrow"))
        self.configure(state="disabled")
        self.bind("<Configure>", self.fit_height)

    def fit_height(self, _event):
        count = self.count("1.0", "end-1c", "displaylines")
        self.configure(height=max(1, (count[0] if count else 0) + 1))


class LocationCard(tk.Frame):
    cache = {}
    def __init__(self, master, location, bg, fg):
        super().__init__(master, bg=bg, padx=6, pady=6)
        self.location, self.closed = location, False
        self.key = (location["latitude"], location["longitude"])
        self.snapshotter = None
        self.results = queue.Queue()
        self.canvas = tk.Canvas(self, width=260, height=150, bg=THEME["surface_alt"], bd=0,
                                highlightthickness=0, cursor="hand2")
        self.canvas.pack()
        self.canvas.create_text(130, 65, text="Загрузка карты…", fill=THEME["text"], font=ui_font(12))
        tk.Label(self, text="📍 Местоположение", bg=bg, fg=fg, font=ui_font(12, "bold")).pack(anchor="w", pady=(6, 0))
        tk.Label(self, text="Яндекс Карты ↗", bg=bg, fg=fg, font=ui_font(11), cursor="hand2").pack(anchor="w")
        bind_click(self, lambda: webbrowser.open(map_url(location)))
        self.bind("<Destroy>", self.cleanup, add="+")
        try:
            if self.key in self.cache:
                self.results.put(self.cache[self.key])
                self.job = self.after(1, self.poll)
                return
            from MapKit import MKMapSnapshotOptions, MKMapSnapshotter, MKCoordinateRegionMake, MKCoordinateSpanMake
            from CoreLocation import CLLocationCoordinate2DMake
            coordinate = CLLocationCoordinate2DMake(location["latitude"], location["longitude"])
            options = MKMapSnapshotOptions.alloc().init()
            options.setSize_((260, 150))
            options.setRegion_(MKCoordinateRegionMake(coordinate, MKCoordinateSpanMake(0.008, 0.008)))
            self.snapshotter = MKMapSnapshotter.alloc().initWithOptions_(options)
            def completed(snapshot, error):
                if self.closed: return
                if snapshot:
                    point = snapshot.pointForCoordinate_(coordinate)
                    value = (bytes(snapshot.image().TIFFRepresentation()), (point.x, point.y))
                    if len(self.cache) >= 64: self.cache.pop(next(iter(self.cache)))
                    self.cache[self.key] = value
                    self.results.put(value)
                else: self.results.put((None, None))
            self.snapshotter.startWithCompletionHandler_(completed)
        except Exception:
            self.results.put((None, None))
        self.job = self.after(100, self.poll)

    def poll(self):
        if self.closed: return
        try:
            data, point = self.results.get_nowait()
        except queue.Empty:
            self.job = self.after(100, self.poll)
            return
        self.canvas.delete("all")
        if data:
            with Image.open(io.BytesIO(data)) as image:
                self.photo = ImageTk.PhotoImage(image.resize((260, 150)))
            self.canvas.create_image(0, 0, image=self.photo, anchor="nw")
            x, y = point
            self.canvas.create_oval(x-7, y-7, x+7, y+7, fill=THEME["danger"], outline="white", width=2)
        else:
            self.canvas.create_text(130, 65, text="Карта недоступна\nНажмите, чтобы открыть",
                                    justify="center", fill=THEME["text"], font=ui_font(12))
        self.job = None

    def cleanup(self, event):
        if event.widget is not self: return
        self.closed = True
        if self.job: self.after_cancel(self.job)
        if self.snapshotter: self.snapshotter.cancel()
