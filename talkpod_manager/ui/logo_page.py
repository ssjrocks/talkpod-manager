"""Boot logo: pick a picture, preview it in the radio's colours, send it."""

import logging

from gi.repository import Adw, Gdk, GdkPixbuf, Gio, GLib, GObject, Gtk, Pango

from .. import logo

LOG = logging.getLogger(__name__)
PREVIEW = 256


def to_pixels(path, mode):
    """Load any picture, crop-to-fill or fit to 128x128, and return RGB565 bytes."""
    src = GdkPixbuf.Pixbuf.new_from_file(str(path))
    src = src.apply_embedded_orientation() or src
    w, h = src.get_width(), src.get_height()
    canvas = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, False, 8, logo.WIDTH, logo.HEIGHT)
    canvas.fill(0x000000FF)
    if mode == "fill":
        scale = max(logo.WIDTH / w, logo.HEIGHT / h)
    else:
        scale = min(logo.WIDTH / w, logo.HEIGHT / h)
    sw, sh = max(1, round(w * scale)), max(1, round(h * scale))
    scaled = src.scale_simple(sw, sh, GdkPixbuf.InterpType.HYPER)
    if scaled.get_has_alpha():
        flat = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, False, 8, sw, sh)
        flat.fill(0x000000FF)
        scaled.composite(flat, 0, 0, sw, sh, 0, 0, 1, 1, GdkPixbuf.InterpType.NEAREST, 255)
        scaled = flat
    ox, oy = (logo.WIDTH - sw) // 2, (logo.HEIGHT - sh) // 2
    # copy the overlapping part (crop when larger, centre when smaller)
    sx, sy = max(0, -ox), max(0, -oy)
    dx, dy = max(0, ox), max(0, oy)
    cw, ch = min(sw - sx, logo.WIDTH - dx), min(sh - sy, logo.HEIGHT - dy)
    scaled.copy_area(sx, sy, cw, ch, canvas, dx, dy)
    return logo.rgb565(canvas.get_pixels(), stride=canvas.get_rowstride(), channels=canvas.get_n_channels())


def preview_texture(pixels):
    """What the radio will show: RGB565 back to RGB, enlarged with hard pixels."""
    rgb = bytearray(logo.WIDTH * logo.HEIGHT * 3)
    for i in range(logo.WIDTH * logo.HEIGHT):
        v = pixels[2 * i] | pixels[2 * i + 1] << 8
        r, g, b = v >> 11 & 0x1F, v >> 5 & 0x3F, v & 0x1F
        rgb[3 * i:3 * i + 3] = bytes(((r << 3) | (r >> 2), (g << 2) | (g >> 4), (b << 3) | (b >> 2)))
    pb = GdkPixbuf.Pixbuf.new_from_bytes(GLib.Bytes.new(bytes(rgb)), GdkPixbuf.Colorspace.RGB, False, 8,
                                         logo.WIDTH, logo.HEIGHT, logo.WIDTH * 3)
    pb = pb.scale_simple(PREVIEW, PREVIEW, GdkPixbuf.InterpType.NEAREST)
    return Gdk.Texture.new_for_pixbuf(pb)


class LogoPage(Gtk.Box):
    """Emits send-requested when the user wants the picture on the radio."""

    __gsignals__ = {
        "send-requested": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "use-logo-requested": (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.path = None
        self.pixels = None
        page = Adw.PreferencesPage()
        self.append(page)

        g = Adw.PreferencesGroup(
            title="Boot logo",
            description="The 128 × 128 picture the radio shows when it's switched on. "
                        "The radio can't send its current picture back, so keep a copy of anything you want to restore.")
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
        choose = Adw.ActionRow(title="Picture", subtitle="Any image file; it's scaled to 128 × 128")
        self.file_label = Gtk.Label(label="", ellipsize=Pango.EllipsizeMode.MIDDLE, max_width_chars=24)
        self.file_label.add_css_class("dim-label")
        btn = Gtk.Button(label="Choose…", valign=Gtk.Align.CENTER)
        btn.connect("clicked", self._choose)
        choose.add_suffix(self.file_label)
        choose.add_suffix(btn)
        g.add(choose)
        self.mode = Adw.ComboRow(title="Fit", model=Gtk.StringList.new(["Crop to fill the screen", "Fit inside (black bars)"]))
        self.mode.connect("notify::selected", lambda *_: self._render())
        g.add(self.mode)

        g = Adw.PreferencesGroup()
        page.add(g)
        self.ponmsg_row = Adw.ActionRow(
            title="The radio shows its battery voltage at power-on",
            subtitle="Menu 49 (Power On Message) must be Logo for the picture to appear.")
        use = Gtk.Button(label="Show logo", valign=Gtk.Align.CENTER)
        use.connect("clicked", lambda *_: self.emit("use-logo-requested"))
        self.ponmsg_row.add_suffix(use)
        self.ponmsg_row.set_visible(False)
        g.add(self.ponmsg_row)
        self.send = Adw.ButtonRow(title="Send picture to radio", sensitive=False)
        self.send.add_css_class("suggested-action")
        self.send.connect("activated", lambda *_: self.emit("send-requested"))
        g.add(self.send)

    def set_power_on_message(self, value):
        """value: the ponmsg setting's current text, or None when no image is loaded."""
        self.ponmsg_row.set_visible(value is not None and str(value).lower() != "logo")

    def _choose(self, *_):
        dialog = Gtk.FileDialog(title="Choose a picture")
        f = Gtk.FileFilter(name="Pictures")
        f.add_pixbuf_formats()
        filters = Gio.ListStore(item_type=Gtk.FileFilter)
        filters.append(f)
        dialog.set_filters(filters)
        dialog.open(self.get_root(), None, self._chosen)

    def _chosen(self, dialog, result):
        try:
            file = dialog.open_finish(result)
        except GLib.Error:
            return
        self.path = file.get_path()
        self.file_label.set_text(file.get_basename())
        self._render()

    def _render(self):
        if not self.path:
            return
        try:
            self.pixels = to_pixels(self.path, "fill" if self.mode.get_selected() == 0 else "fit")
        except GLib.Error as e:
            self.pixels = None
            self.file_label.set_text(f"Can't read: {e.message}")
            self.stack.set_visible_child_name("empty")
            self.send.set_sensitive(False)
            return
        self.picture.set_paintable(preview_texture(self.pixels))
        self.stack.set_visible_child_name("picture")
        self.send.set_sensitive(True)

