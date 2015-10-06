#! /usr/bin/python
# -*- coding: utf-8 -*-



from gi.repository import GObject, Gtk, GdkX11, GLib, Gdk

from tools import colors, is_float, seconds_to_hms_str

import os
import cairo


class DObject(object):
    def __init__(self, figure, x1, y1, x2, y2, type_ob, probability_ob):
        self.figure = figure
        self.x1 = int(x1)
        self.x2 = int(x2)
        self.y1 = int(y1)
        self.y2 = int(y2)
        self.type = type_ob
        self.probability = float(probability_ob)


class DFrame(object):
    def __init__(self, second, frame_path, main_widget):
        print(second)
        self.orig_height = 0
        self.orig_width = 0
        self.ratio = 0

        self.second = second
        self.main_widget = main_widget
        self.frame_path = None
        self.dobjects = list()
        self.x_y_coords = None
        self.len_dobjects = 0
        self.average_probability = None
        self.visible = True

        self.cairo_image = None
        self.cairo_image_clean = None
        self.ctx = None

        self.add_frame_path(frame_path)

        self.da = None  # Gtk.DrawingArea()
        self.toggle_show_button = None
        self.da_visible = True

        self.added_to_listbox = False
        self.row = Gtk.ListBoxRow()
        self.event_box = Gtk.EventBox()
        #self.event_box.set_above_child(True)
        self.event_box.connect("button-press-event", self.main_widget.on_button_press_event)
        self.vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.event_box.set_border_width(1)
        self.event_box.add(self.vbox)
        self.row.add(self.event_box)

        self.event_box.modify_bg(Gtk.StateType.NORMAL, colors["light_gray"])
        # self.row.add(self.vbox)

    def add_dobject(self, dobject):
        self.dobjects.append(dobject)
        self.len_dobjects += 1
        if is_float(dobject.probability):
            if not self.average_probability:
                self.average_probability = dobject.probability
            else:
                self.average_probability = (self.average_probability + dobject.probability) / 2.

    def set_coords(self, coords):
        self.x_y_coords = coords

    def show_hide_da(self, button):

        if self.da_visible:
            self.da.hide()
            button.set_label("Show")
        else:
            self.da.show()
            button.set_label("Hide")
        self.da_visible = not self.da_visible

    def get_listbox_item(self, container=None):

        self.da = Gtk.DrawingArea()
        # self.toggle_show_button = Gtk.Button(label="Hide")
        self.da.set_size_request(100, 100. / self.ratio)
        self.da.connect("draw", self.on_draw)
        #self.da.connect("size-allocate", self.on_size_allocate)

        # self.toggle_show_button.connect("clicked", lambda b: self.show_hide_da(b))
        # self.da_visible = True
        # self.vbox.pack_start(self.toggle_show_button, False, False, 0)
        # #self.da.connect("size-allocate", self.on_size_allocate)

        self.vbox.pack_start(self.da, True, False, 0)

        #self.vbox.pack_start(label_frame, True, False, 0)
        hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=3)
        self.vbox.pack_start(hbox, True, False, 0)
        label_second = Gtk.Label(seconds_to_hms_str(self.second))
        label_len_obj = Gtk.Label(self.len_dobjects)

        button_check_visibility = Gtk.CheckButton()
        button_check_visibility.connect("toggled", self.on_toggled)

        #button_check_visibility.set_active(True)

        hbox.pack_start(label_second, True, False, 0)
        hbox.pack_start(Gtk.Label(u"Об'єктів:"), False, True, 0)
        hbox.pack_start(label_len_obj, True, False, 0)
        hbox.pack_end(button_check_visibility, False, False, 0)

        #import ipdb; ipdb.set_trace()
        self.added_to_listbox = True
        self.row.show_all()
        return self.row
        # if container:
        #     container.add(self.row)

    def on_toggled(self, button):
        print("on ttogled")
        state = button.get_active()
        button.set_active(True if state else False)
        self.da_visible = False if state else True

    def add_frame_path(self, frame_path):

        if frame_path and os.path.isfile(frame_path):
            self.frame_path = frame_path
            self.add_frame_from_path_cai(frame_path)

    def add_frame_from_path_cai(self, frame_path):

        self.frame_path = frame_path
        self.cairo_image = cairo.ImageSurface.create_from_png(frame_path)
        # self.cairo_image_clear = cairo.ImageSurface.create_from_png(frame_path)

        self.ctx = cairo.Context(self.cairo_image)
        # self.ctx_clean = cairo.Context(self.cairo_image_clear)

        self.orig_width = self.cairo_image.get_width()
        self.orig_height = self.cairo_image.get_height()

        self.ratio = float(self.orig_width) / self.orig_height

    def draw_dobjects(self):

        for do in self.dobjects:
            self.ctx.rectangle(do.x1, do.y1, do.x2 - do.x1, do.y2 - do.y1)
            self.ctx.set_line_width(3)
            self.ctx.set_source_rgb(1, 1, 0)
            self.ctx.stroke()

            #self.ctx.save()

    def save_picture(self, path):

        self.ctx.save(path)

    def on_draw(self, widget_da, cairo_context):

        #if self.main_widget.processing_flag == False:
        self.main_widget.processing_flag = True
        width = widget_da.get_allocation().width - 10
        self.draw_cairo_image(cairo_context, self.cairo_image, 5, 5, width, width / self.ratio)
        #self.draw_cairo_image(cairo_context, self.cairo_image_clean, 5, 5, width, width/self.ratio)
        self.main_widget.processing_flag = False

    def on_size_allocate(self, widget_da, allocation):
        print("on_size_allocate")
        cairo_context = widget_da.get_window().cairo_create()
        width = allocation.width - 10

        self.draw_cairo_image(cairo_context, self.cairo_image, 5, 5, width, width / self.ratio)

    def draw_cairo_image(self, ctx, image_surface, top, left, width, height):
        """Draw a scaled image on a given context."""

        width_ratio = float(width) / float(self.orig_width)
        height_ratio = float(height) / float(self.orig_height)
        scale_xy = min(height_ratio, width_ratio)

        #ctx.save()
        ctx.translate(left, top)
        ctx.scale(scale_xy, scale_xy)
        ctx.set_source_surface(image_surface)

        ctx.paint()
        #ctx.restore()

        self.da.set_size_request(-1, height)
