"""Boot splash (Talkpod Super Firmware): pick a picture or animation, fit it to the screen, preview
it in the radio's colours, see how much room it takes, send it."""

import logging

from gi.repository import Adw, Gdk, GdkPixbuf, Gio, GLib, GObject, Gtk, Pango

from .. import splash
from . import worker

LOG = logging.getLogger(__name__)
PREVIEW = 256
STILL_LABELS = [f"{s} second{'s' if s > 1 else ''}" for s in splash.STILL_SECONDS]
EVERY = [1, 2, 3]
LIMITS = [
    ("Needs Talkpod Super Firmware 1.0 or later",
     "Stock firmware has no animation: it shows a still picture, set on the Logo page."),
    ("128 × 128 pixels, 16-bit colour",
     "Other sizes are resized as chosen above. Each frame can have up to 256 colours; more are reduced."),
    ("Plays at power-on",
     "Once, or as many times as \u201cPlay it\u201d says; then the radio carries on as usual. Any key skips it."),
    ("Up to 15 seconds of animation and 500 KB",
     "Longer animations are cut at 15 s. Only what changes between frames is stored, so simple "
     "animations take little room."),
    ("Frames of 20 ms or longer",
     "The radio takes about 22 ms to redraw the whole screen, so very fast animations play a little slower."),
    ("Sending takes about a minute per 100 KB",
     "The programming cable runs at 57,600 baud, and everything is read back to check it."),
]


def _texture(rgb):
    pb = GdkPixbuf.Pixbuf.new_from_bytes(GLib.Bytes.new(rgb), GdkPixbuf.Colorspace.RGB, False, 8,
                                         splash.SIZE, splash.SIZE, splash.SIZE * 3)
    return Gdk.Texture.new_for_pixbuf(pb.scale_simple(PREVIEW, PREVIEW, GdkPixbuf.InterpType.NEAREST))


def _rgb_bytes(values):
    lut = {c: bytes(splash.to_rgb(c)) for c in set(values)}
    return b"".join(lut[c] for c in values)


def _duration(ms):
    return f"{ms / 1000:.1f} s" if ms < 60000 else f"{ms // 60000} min {ms % 60000 // 1000} s"


def send_time(seconds):
    if seconds < 60:
        return f"about {max(5, round(seconds / 5) * 5)} seconds"
    minutes = round(seconds / 30) / 2
    return f"about {minutes:g} minute{'s' if minutes > 1 else ''}"


class SplashPage(Gtk.Box):
    """Emits send-requested, play-requested and remove-requested; the window talks to the radio."""

    __gsignals__ = {
        "send-requested": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "play-requested": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "remove-requested": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "firmware-requested": (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.path = None
        self.source = None
        self.splash = None
        self.radio_ok = False           # a cable and nothing else going on: set by the window
        self._generation = 0
        self._textures, self._delays, self._frame, self._timer = [], [], 0, 0

        page = Adw.PreferencesPage()
        self.append(page)

        g = Adw.PreferencesGroup(
            title="Boot splash",
            description="For radios running Talkpod Super Firmware: an animation or picture the radio plays once "
                        "when it's switched on. The preview shows it in the radio's colours.")
        page.add(g)
        frame = Gtk.Frame(halign=Gtk.Align.CENTER, margin_top=6, margin_bottom=12)
        self.picture = Gtk.Picture(can_shrink=False, width_request=PREVIEW, height_request=PREVIEW)
        self.placeholder = Gtk.Label(label="No picture chosen", width_request=PREVIEW, height_request=PREVIEW)
        self.placeholder.add_css_class("dim-label")
        self.stack = Gtk.Stack()
        self.stack.add_named(self.placeholder, "empty")
        self.stack.add_named(self.picture, "picture")
        frame.set_child(self.stack)
        g.add(frame)

        g = Adw.PreferencesGroup()
        page.add(g)
        choose = Adw.ActionRow(title="Picture or animation", subtitle="GIF, PNG, JPEG, WebP and most other pictures")
        self.file_label = Gtk.Label(label="", ellipsize=Pango.EllipsizeMode.MIDDLE, max_width_chars=24)
        self.file_label.add_css_class("dim-label")
        btn = Gtk.Button(label="Choose…", valign=Gtk.Align.CENTER)
        btn.connect("clicked", self._choose)
        choose.add_suffix(self.file_label)
        choose.add_suffix(btn)
        g.add(choose)
        self.size_row = Adw.ActionRow(title="Size", visible=False)
        g.add(self.size_row)
        self.fit_row = Adw.ComboRow(title="Resize", visible=False,
                                    model=Gtk.StringList.new([label for _, label, _ in splash.FIT_MODES]))
        self.fit_row.set_subtitle(splash.FIT_MODES[0][2])
        self.fit_row.connect("notify::selected", self._fit_changed)
        g.add(self.fit_row)
        self.bg_row = Adw.ActionRow(title="Background",
                                    subtitle="Around a picture that doesn't fill the screen, and behind transparent parts")
        self.bg_button = Gtk.ColorDialogButton(dialog=Gtk.ColorDialog(with_alpha=False), valign=Gtk.Align.CENTER)
        self.bg_button.set_rgba(Gdk.RGBA(red=0, green=0, blue=0, alpha=1))
        self.bg_button.connect("notify::rgba", lambda *_: self._rebuild())
        self.bg_row.add_suffix(self.bg_button)
        g.add(self.bg_row)
        self.still_row = Adw.ComboRow(title="Show the picture for", visible=False,
                                      model=Gtk.StringList.new(STILL_LABELS))
        self.still_row.set_selected(splash.STILL_SECONDS.index(3))
        self.still_row.connect("notify::selected", lambda *_: self._rebuild())
        g.add(self.still_row)
        self.every_row = Adw.ComboRow(title="Frames", visible=False,
                                      subtitle="Fewer frames take less room and send faster; the animation keeps its length",
                                      model=Gtk.StringList.new(["All frames", "Every 2nd frame", "Every 3rd frame"]))
        self.every_row.connect("notify::selected", lambda *_: self._rebuild())
        g.add(self.every_row)
        self.plays_row = Adw.ComboRow(title="Play it", visible=False,
                                      subtitle="Repeats take no extra room (Super Firmware 1.1 and later)",
                                      model=Gtk.StringList.new(["Once"] + [f"{n} times" for n in splash.PLAYS[1:]]))
        self.plays_row.connect("notify::selected", lambda *_: self._rebuild())
        g.add(self.plays_row)
        self.hold_row = Adw.ComboRow(title="Hold the last frame", visible=False,
                                     subtitle="Keeps the end of the animation on screen a little longer",
                                     model=Gtk.StringList.new(["No"] + [f"{n} s longer" for n in splash.HOLD_SECONDS[1:]]))
        self.hold_row.connect("notify::selected", lambda *_: self._rebuild())
        g.add(self.hold_row)

        g = Adw.PreferencesGroup(title="On the radio")
        page.add(g)
        self.room_row = Adw.ActionRow(title="Room used", subtitle="Choose a picture first")
        self.room_bar = Gtk.LevelBar(min_value=0, max_value=100, valign=Gtk.Align.CENTER, width_request=140)
        for name in (Gtk.LEVEL_BAR_OFFSET_LOW, Gtk.LEVEL_BAR_OFFSET_HIGH, Gtk.LEVEL_BAR_OFFSET_FULL):
            self.room_bar.remove_offset_value(name)     # plain accent colour, not "low battery" styles
        self.room_row.add_suffix(self.room_bar)
        g.add(self.room_row)
        self.send = Adw.ButtonRow(title="Send to radio", sensitive=False)
        self.send.add_css_class("suggested-action")
        self.send.connect("activated", lambda *_: self.emit("send-requested"))
        g.add(self.send)
        self.play = Adw.ButtonRow(title="Play the radio's splash now", sensitive=False)
        self.play.connect("activated", lambda *_: self.emit("play-requested"))
        g.add(self.play)
        self.remove = Adw.ButtonRow(title="Remove the splash from the radio", sensitive=False)
        self.remove.add_css_class("destructive-action")
        self.remove.connect("activated", lambda *_: self.emit("remove-requested"))
        g.add(self.remove)

        g = Adw.PreferencesGroup(title="Limits")
        page.add(g)
        for i, (title, text) in enumerate(LIMITS):
            row = Adw.ActionRow(title=title, subtitle=text, activatable=False)
            row.add_prefix(Gtk.Image(icon_name="dialog-information-symbolic"))
            if i == 0:                  # the firmware itself: offered in Flash firmware…
                get = Gtk.Button(label="Get it…", valign=Gtk.Align.CENTER)
                get.connect("clicked", lambda *_: self.emit("firmware-requested"))
                row.add_suffix(get)
            g.add(row)

        self.connect("map", lambda *_: self._animate())
        self.connect("unmap", lambda *_: self._stop())

    # --- state the window sets -----------------------------------------------------------------

    def set_radio_ok(self, ok):
        self.radio_ok = ok
        self._sync_buttons()

    def _sync_buttons(self):
        ready = self.splash is not None and self.splash.fits
        self.send.set_sensitive(self.radio_ok and ready)
        self.play.set_sensitive(self.radio_ok)
        self.remove.set_sensitive(self.radio_ok)

    # --- choosing and building -----------------------------------------------------------------

    def _choose(self, *_):
        dialog = Gtk.FileDialog(title="Choose a picture or animation")
        f = Gtk.FileFilter(name="Pictures and animations")
        f.add_pixbuf_formats()
        for pattern in ("*.gif", "*.png", "*.apng", "*.webp", "*.jpg", "*.jpeg", "*.bmp"):
            f.add_pattern(pattern)
        filters = Gio.ListStore(item_type=Gtk.FileFilter)
        filters.append(f)
        dialog.set_filters(filters)
        dialog.open(self.get_root(), None, self._chosen)

    def _chosen(self, dialog, result):
        try:
            file = dialog.open_finish(result)
        except GLib.Error:
            return
        self.load(file.get_path())

    def load(self, path):
        """Reads the picture (on a thread) and builds the splash from it."""
        self.path = path
        self.source = None
        self.file_label.set_text(GLib.path_get_basename(path))
        self._rebuild()

    def _fit_changed(self, *_):
        self.fit_row.set_subtitle(splash.FIT_MODES[self.fit_row.get_selected()][2])
        self._rebuild()

    def _options(self):
        rgba = self.bg_button.get_rgba()
        bg = tuple(round(v * 255) for v in (rgba.red, rgba.green, rgba.blue))
        return dict(mode=splash.FIT_MODES[self.fit_row.get_selected()][0], bg=bg,
                    still_ms=splash.STILL_SECONDS[self.still_row.get_selected()] * 1000,
                    every=EVERY[self.every_row.get_selected()],
                    plays=splash.PLAYS[self.plays_row.get_selected()],
                    hold_ms=splash.HOLD_SECONDS[self.hold_row.get_selected()] * 1000)

    def _rebuild(self):
        if not self.path:
            return
        self._generation += 1
        gen, path, source, opts = self._generation, self.path, self.source, self._options()
        self.splash = None
        self._sync_buttons()
        self.room_row.set_subtitle("Preparing…")

        def job(_progress):
            src = source or splash.load(path)
            built = splash.build(src, **opts)
            return src, built, [_rgb_bytes(values) for values, _ in built.frames]

        def done(result):               # an older choice's result is dropped
            if gen == self._generation:
                self._built(*result)

        def failed(e):
            if gen == self._generation:
                self._failed(e)

        worker.run(job, done, failed)

    def _failed(self, e):
        if not isinstance(e, splash.SplashError):
            LOG.exception("preparing the splash failed", exc_info=e)
        self.source = self.splash = None
        self.file_label.set_text("Can't read that file")
        self.room_row.set_subtitle(str(e))
        self.room_bar.set_value(0)
        for row in (self.size_row, self.fit_row, self.still_row, self.every_row, self.plays_row, self.hold_row):
            row.set_visible(False)
        self._stop()
        self.stack.set_visible_child_name("empty")
        self._sync_buttons()

    def _built(self, src, built, rgb_frames):
        self.source, self.splash = src, built
        what = (f"{len(src.frames)} frames · {_duration(src.duration_ms)}" + (" (cut at 15 s)" if src.truncated else "")
                if src.animated else "still picture")
        self.size_row.set_subtitle(
            f"{src.width} × {src.height} pixels · {what}"
            + ("" if src.needs_resize else " · exactly the radio's screen size, used as it is"))
        if src.needs_resize:
            self.size_row.set_title("Size: not 128 × 128, so it's resized")
        else:
            self.size_row.set_title("Size")
        self.size_row.set_visible(True)
        self.fit_row.set_visible(src.needs_resize)
        self.still_row.set_visible(not src.animated)
        self.every_row.set_visible(src.animated)
        self.plays_row.set_visible(src.animated)
        self.hold_row.set_visible(src.animated)

        kb = (len(built.blob) + 1023) // 1024
        if built.fits:
            self.room_row.set_subtitle(f"{kb} KB of 500 KB ({built.percent:.0f} %) · sending takes "
                                       f"{send_time(built.upload_seconds)} · plays for {_duration(built.duration_ms)}")
        else:
            self.room_row.set_subtitle(f"{kb} KB: too big for the radio's 500 KB. Use fewer frames, a shorter "
                                       "animation, or one with fewer changes between frames.")
        self.room_bar.set_value(min(100, built.percent))

        self._stop()
        self._textures = [_texture(rgb) for rgb in rgb_frames]
        self._delays = [d for _, d in built.frames]
        self._frame = 0
        self.picture.set_paintable(self._textures[0])
        self.stack.set_visible_child_name("picture")
        self._animate()
        self._sync_buttons()

    # --- the preview's animation ---------------------------------------------------------------

    def _stop(self):
        if self._timer:
            GLib.source_remove(self._timer)
            self._timer = 0

    def _animate(self):
        """plays the frames with their delays, then holds the last one for a second and starts again"""
        self._stop()
        if len(self._textures) < 2 or not self.get_mapped():
            return

        def next_frame():
            self._frame = (self._frame + 1) % len(self._textures)
            self.picture.set_paintable(self._textures[self._frame])
            pause = 1000 if self._frame == len(self._textures) - 1 else 0
            self._timer = GLib.timeout_add(self._delays[self._frame] + pause, next_frame)
            return False

        self._timer = GLib.timeout_add(self._delays[self._frame], next_frame)
