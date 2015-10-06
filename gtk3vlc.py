#! /usr/bin/python
# -*- coding: utf-8 -*-
#
"""VLC Gtk Widget classes + example application.

This module provides two helper classes, to ease the embedding of a
VLC component inside a pygtk application.

VLCWidget is a simple VLC widget.

DecoratedVLCWidget provides simple player controls.

When called as an application, it behaves as a video player.

$Id$
"""

import os
import sys
import ntpath
import time
import datetime
import tempfile
import subprocess
import uuid
import random

from gi.repository import GObject, Gtk, Gdk  # cairo  pygobject # as gobject

#sys.path.append(os.path.dirname(os.path.realpath(__file__)))
import multiprocessing as mp
from threading import Thread

# from mvp import MultiVideoPlayer
from tools import (SettingsWindowWidgets, FilterWindowWidgets, StatusWindowWidgets, WarningDialog,
                   create_main_ui_manager,
                   time_to_seconds, seconds_to_hms_str,
                   is_int, is_float,
                   sorting_callbacks,
                   open_file_dialog_filters,
                   colors)

from containers import DFrame, DObject

GObject.threads_init()

this_debug = True

import vlc

import cv2
import caffe

from gettext import gettext as _
from collections import defaultdict


def check_and_create_dir(path):
    if not os.path.isdir(path):
        os.makedirs(path)


def get_filename(path):
    head, tail = ntpath.split(path)
    return tail or ntpath.basename(head)

TMP_DIR = tempfile.gettempdir()
framesRootDirectory = "trackedFrames"
homeDirectory = os.path.expanduser("~")
framesRootDirPath = os.path.join(homeDirectory, framesRootDirectory)
check_and_create_dir(framesRootDirPath)

# caffe prefs
caffe.set_mode_gpu()
calc_mode = 'GPU'

factor = 0.8

step = 4
batch = 128

CURRENT_DIRECTORY = os.path.dirname(__file__)
print >> sys.stderr, CURRENT_DIRECTORY
# VLAD
# weights = "predator_gray64_ob_5_iter_70000_vl.caffemodel"
# net_proto = "predator_gray64_ob_deploy_vl.prototxt"
# OSTAP
weights = os.path.join(CURRENT_DIRECTORY, "nets/predator_gray64_ob_5_iter_70000.caffemodel")
net_proto = os.path.join(CURRENT_DIRECTORY, "nets/predator_gray64_ob_deploy.prototxt")


classifier = caffe.Classifier(net_proto, weights, raw_scale=255.0)


# Create a single vlc.Instance() to be shared by (possible) multiple players.
instance = vlc.Instance()


class VLCWidget(Gtk.DrawingArea):
    """Simple VLC widget.

    Its player can be controlled through the 'player' attribute, which
    is a vlc.MediaPlayer() instance.
    """

    def __init__(self, paned, *p):
        Gtk.DrawingArea.__init__(self)
        self.player = instance.media_player_new()
        self.ui = paned

        def handle_embed(*args):
            print("handle_embed")
            if sys.platform == 'win32':
                print("set_hwnd")
                self.player.set_hwnd(self.get_window().handle)
                #self.player.set_hwnd(self.widget.window.handle)
            else:
                print("set_xid")
                self.player.set_xwindow(self.get_window().get_xid())
                #self.player.set_xwindow(self.widget.window.xid)
            return True

        self.connect("map", handle_embed)
        # self.set_size_request(320, 200)
        # self.drawing_area.add_events(Gdk.EventMask.BUTTON_PRESS_MASK)


def pringles(text, x):

    print text, str(x)

class DecoratedVLCWidget(Gtk.Paned):  # (Gtk.HBox):
    """Decorated VLC widget.

    VLC widget decorated with a player control .

    Its player can be controlled through the 'player' attribute, which
    is a Player instance.
    """

    def __init__(self, main_class, *p):

        Gtk.Paned.__init__(self)
        self.set_border_width(10)
        # self.set_property("set_wide_handle", 200)
        self.main = main_class
        self.time = time.time()
        self.current_dialog = None

        # PLAYER
        self._vlc_widget = VLCWidget(self, *p)
        self.player = self._vlc_widget.player
        # self._vlc_widget.connect("button-press-event", self.play_pause_click)

        # CONTAINERS
        self._left_panel_vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.player_visible = True
        self._vbox_player = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.hbox_time = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        self.hbox_slider = Gtk.HBox(False, 10, orientation=Gtk.Orientation.HORIZONTAL)
        self.hbox_toolbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)

        self.thread = None
        self.main_close_request = False
        self.adding_frames  = False
        self.detection_pause_request = False
        self.detection_paused = False
        self.detection_completed = False
        self.processing_flag = False
        self.allow_process_settings_window = True
        self.allow_main_close = True
        self.tmp_images = list()

        self.results_dir_path = framesRootDirPath

        self.detection_progress = None
        self.detection_time_to_end = None
        self.detection_flag = True
        # self.status_widgets = StatusBoxWidgets(self)
        # self.status_widgets.button_stop.connect("clicked", lambda b: self.stop_detecting)

        self.thumbnails_visible = False
        self.visibility_flag = True
        self._vbox_thumbnails = Gtk.VBox()

        # SORT PREFERENCES
        self.sort_order_ascending = True
        self.current_sort_func = self.sorting_by_time_default
        self.sort_cb = sorting_callbacks['ascending']

        # MENUS
        action_group = Gtk.ActionGroup("my_actions")
        self.add_file_menu_actions(action_group)
        self.add_view_menu_actions(action_group)
        self.add_context_menu_actions(action_group)
        self.radio_sort_order = action_group.get_action("SortRadioAscending")


        uimanager = create_main_ui_manager(self.main.main_window)
        uimanager.insert_action_group(action_group)

        self._menubar = uimanager.get_widget("/MenuBar")
        #self.sort_menu = uimanager.get_widget("/ViewMenuBar")
        self.popup = uimanager.get_widget("/PopupMenu")

        #self.progressbar = self.get_progressbar()
        #self.gp = GObject.timeout_add(100, self.update_progressbar)
        #self.hbox_progress.pack_start(self.progressbar, True, True, 0)
        #self.progressbar.connect("clicked", lambda pb: self.set_progressbar)

        # CURRENT|TOTAL TIME
        self.label_current_time = Gtk.Label("00:00:00")
        self.label_separator_time = Gtk.Label("-")
        self.label_total_time = Gtk.Label('00:00:00')

        # SLIDER
        self.slider_prev_position = 0
        self.slider_adj = Gtk.Adjustment(0.0, 0.0, 101.0, 0.1, 1.0, 1.0)
        self.slider = self.get_slider()
        self.slider_adj.connect("value_changed", self.seek_slider_position)

        self.gs = GObject.timeout_add(100, self.update_slider)

        # TOOLBAR
        self._toolbar = self.get_player_control_toolbar()
        # self.combo_view = self.get_combo_view()
        self.switch_thumbnails = self.get_thumbnails_switch()

        # LIST BOX
        self.scrollable_window = self.get_scrollable_window()
        self.listbox_thumbnails = self.get_player_listbox()
        self.listbox_thumbnails.connect("row-selected", self.on_row_activated)
        self.listbox_item_time_clicked = time.time()

        # _______________________________________________________________
        # ***************************************************************
        # ===============================================================
        # PACK PLAYER CONTROLS
        self.pack_items()

        # SETTINGS
        self.min_probability = 0.970
        self.settings_widgets = SettingsWindowWidgets()  # self.builder)
        self.settings_widgets_adjust()

        self.filter_widgets = FilterWindowWidgets()
        self.filter_widgets_adjust()

        self.status_widgets = StatusWindowWidgets(self)

        self.init_video_attrs = ["video_name", "video_path", "video_duration_sec", "video_size",
                                 "telemetry_path",
                                 "results_file_path", "results_fileName",
                                 "frame_seconds", "cut_from_sec", "cut_to_sec"]
        self.results_file = None
        self.init_video_settings()

        self.detecting_time_start = None
        self.detecting_time_end = None

        self.process_from_beginning = True

        #CUT_SETTINGS
        self.cut_step = 30  #15  # seconds

        #CAFFE_SETTINGS
        self.size = 64
        self.ss = int(self.size // step)
        self.save_res_to_file = True

        self.max_frame_objects = 0
        self.detected_frames = dict()

        # SHOW SECTION
        if self.player_visible:
            self._vbox_player.show_all()
        # self.show_status(False)
        if self.thumbnails_visible:
            self._vbox_thumbnails.show_all()

        self._left_panel_vbox.show()
        self.show()
        self.lb_update = GObject.timeout_add(1000, self.check_and_add_frames)
        self.main_close_check = GObject.timeout_add(1000, self.close_check)

    def pack_items(self):

        self.pack1(self._vbox_player, True, False)
        # self.pack1(self._left_panel_vbox, True, True)
        # self._left_panel_vbox.pack_start(self.status_widgets.main_box, True, True, 0)
        # self._left_panel_vbox.pack_start(self._vbox_player, True, True, 0)

        self.hbox_time.pack_end(self.label_total_time, False, True, 2)
        self.hbox_time.pack_end(self.label_separator_time, False, True, 2)
        self.hbox_time.pack_end(self.label_current_time, False, True, 2)

        self.hbox_slider.pack_start(self.slider, True, True, 0)

        self.hbox_toolbar.pack_start(self._toolbar, False, False, 0)
        self.hbox_toolbar.pack_end(self.switch_thumbnails, False, False, 0)
        self.hbox_toolbar.pack_end(Gtk.Label(u"Результати обробки"), False, False, 5)  # ображення

        #self.hbox_toolbar.pack_end(self.combo_view, False, False, 0)

        self._vbox_player.pack_start(self._menubar, False, False, 0)
        self._vbox_player.pack_start(self._vlc_widget, True, True, 0)
        self._vbox_player.pack_start(self.hbox_time, False, True, 0)
        self._vbox_player.pack_start(self.hbox_slider, False, True, 0)
        self._vbox_player.pack_start(self.hbox_toolbar, False, False, 0)

        #PACK THUMBNAILS
        self.pack2(self._vbox_thumbnails, False, False)  # True)

        self.scrollable_window.add_with_viewport(self.listbox_thumbnails)

        self._vbox_thumbnails.pack_start(self.popup, False, False, 0)
        self._vbox_thumbnails.pack_start(self.scrollable_window, True, True, 0)

        # _______________________________________________________________
        # ***************************************************************
        # ===============================================================

    def show_process_settings(self, show=False):

        print ("show process settings window")
        if self.allow_process_settings_window:
            print ("process settings window allowed")
            if show:
                print("show settings")
                self.settings_widgets.show_settings()
            else:
                print("hide settings")
                self.settings_widgets.hide_settings()
        else:
            self.show_video_close_warning_dialog()

    def show_video_close_warning_dialog(self):

        dialog = WarningDialog(self.main.main_window, u"Для роботи з наступним відео слід\n"
                                                      u"завершити роботу з теперішнім.\n"
                                                      u"Бажаєте закрити відео?")
        response = dialog.run()

        if response == Gtk.ResponseType.OK:
            dialog.destroy()
            self.close_video()
            self.settings_widgets.show_settings()
            return True
        elif response == Gtk.ResponseType.CANCEL:
            print("The Cancel button was clicked")

        dialog.destroy()
        return False

    def show_player_close_warning_dialog(self):

        dialog = WarningDialog(self.main.main_window, u"Для завершення роботи програми необхідно перервати процес "
                                                      u"обробки.\n"
                                                      u"Ви дійсно бажаєте завершити роботу?")
        response = dialog.run()

        if response == Gtk.ResponseType.OK:
            dialog.destroy()
            self.allow_main_close = True
            self.detection_pause_request = True
            self.main_close_request = True
            # self.main.exit()
            return True
        else:
            self.main_close_request = False
            dialog.destroy()
            return False

    def check_and_add_frames(self):

        #detected_frames = getattr(self, "detected_frames", None)
        if self.adding_frames:
            return True

        self.adding_frames = True
        if self.detected_frames:
            for second, dframe in self.detected_frames.items():
                if self.video_path:
                    if not dframe.added_to_listbox:
                        print >> sys.stderr, "ADDING frame at %s to listbox" % str(dframe.second)
                        dframe.added_to_listbox = True
                        row = dframe.get_listbox_item()
                        self.listbox_thumbnails.add(row)

                        if not self.thumbnails_visible:
                            self.update_thumbnails_visibility(True)

        self.adding_frames = False
        return True

    def close_check(self):

        if self.main_close_request:
            #DIALOG
            if self.thread:
                if not self.thread.is_alive():
                    self.main.exit()
            else:
                self.main.exit()
        return True

    def on_detecting_start(self):

        self.status_widgets.on_detetection_start()
        self.detecting_time_start = time.time()
        self.detection_paused = False
        self.detection_pause_request = False
        self.allow_process_settings_window = False
        self.allow_main_close = False
        #self.status_widgets.on_detetection_start()

    def on_detecting_pause(self):

        self.status_widgets.on_detection_pause()
        self.detection_paused = True
        self.detection_pause_request = False
        # self.allow_main_close = True
        print("\n\t\ton_detecting_pause\n")

    def on_detecting_end(self):

        self.status_widgets.on_detection_completed()
        self.detection_paused = False
        self.detection_pause_request = False
        self.filter_widgets.entry_obj_max.set_text(str(self.max_frame_objects))
        self.allow_process_settings_window = True
        self.allow_main_close = True
        self.player.set_position(0)
        self.player.play()

    def on_switch_activated(self, switch, gparam):

        if self.detected_frames:
            if switch.get_active():
                self.thumbnails_visible = True
                self._vbox_thumbnails.show_all()
            else:
                self.thumbnails_visible = False
                self._vbox_thumbnails.hide()
        else:
            switch.set_active(False)

    def update_thumbnails_visibility(self, visible=True):

        if visible:
            self.thumbnails_visible = True
            self._vbox_thumbnails.show_all()
            self.switch_thumbnails.set_active(True)
        else:
            self.thumbnails_visible = False
            self._vbox_thumbnails.hide()
            self.switch_thumbnails.set_active(False)

    def on_button_press_event(self, widget, event):
        # Check if right mouse button was preseed
        if event.type == Gdk.EventType.BUTTON_PRESS:
            if event.button == 1:
                current_time = time.time()
                if current_time - self.listbox_item_time_clicked < 0.3:
                    frame_obj = self.get_listbox_selected_dframe()

                    if not frame_obj:
                        return False

                    tmp_name = uuid.uuid1().hex
                    tmp_path = os.path.join(TMP_DIR, tmp_name)

                    print tmp_path
                    frame_obj.cairo_image.write_to_png(tmp_path)
                    if os.path.isfile(tmp_path):
                        command = "eog -f %s" % tmp_path
                        subprocess.Popen(command.split(), stdout=subprocess.PIPE)
                        self.tmp_images.append(tmp_path)
                    else:
                        print "no tmp"
                self.listbox_item_time_clicked = current_time
            elif event.button == 2:
                frame_obj = self.get_listbox_selected_dframe()
                if not frame_obj:
                    return False
                command = "eog -f %s" % frame_obj.frame_path
                subprocess.Popen(command.split(), stdout=subprocess.PIPE)

            elif event.button == 3:
                print 3
                # get listbox item
                try:
                    switch_to = widget.get_parent()
                    self.listbox_thumbnails.select_row(switch_to)
                    self.popup.popup(None, None, None, None, event.button, event.time)
                except AttributeError, e:
                    pass

        return False
        #return True  # event has been handled

    def on_row_activated(self, widget, row):
        # print("\n%s\n" % str("on row activated"))
        try:
            children = row.get_child().get_children()[0].get_children()[1].get_children()
            second = time_to_seconds(children[0].get_text())
            self.player.set_position(self.second_to_position(second))
        except AttributeError, e:
            pass

    def next_previous_frame(self, next=True):

        switch_to = None
        all_rows = self.listbox_thumbnails.get_children()
        selected = self.listbox_thumbnails.get_selected_row()
        if selected:
            res = [(i, child) for i, child in enumerate(all_rows) if child is selected]
            selected_idx = res[0][0]

            if next and len(all_rows) > (selected_idx + 1):
                switch_to = all_rows[selected_idx + 1]
            elif not next and selected_idx != 0:
                switch_to = all_rows[selected_idx - 1]

            if switch_to:
                self.listbox_thumbnails.select_row(switch_to)
                # chd2 = next_row.get_child().get_children()[0].get_children()[1].get_children()
                #
                #
                # print "selected - %s" % children[0].get_text()
                # print "next - %s" % chd2[0].get_text()
                #
                # pass

    def add_file_menu_actions(self, action_group):

        action_filemenu = Gtk.Action("FileMenu", u"Файл", None, None)
        action_group.add_action(action_filemenu)

        action_group.add_actions([
            ("FileProcess", None, u"Обробка відео", "<control>D", u"Обробити відео",
             lambda m: self.show_process_settings(True)),
            ("FileQuit", None, u"Вихід", "<control>Q", u"Закрити програму",
             lambda m: self.main.exit())#Gtk.main_quit)
        ])

    def add_view_menu_actions(self, action_group):

        action_filemenu = Gtk.Action("ViewMenu", u"Вигляд", None, None)
        action_group.add_action(action_filemenu)

        three = Gtk.ToggleAction("ShowHideSelected", u"Приховати відмічені кадри", "<control>H",
                                 u"Приховати зображення", )
        three.connect("toggled", lambda m: self.hide_selected())
        action_group.add_action(three)

        action_group.add_actions([
            ("FilterMenu", None, u"Фільтрування", "<control>F", u"Фільтрувати зображення",
             lambda m: self.filter_widgets.show_filters()),
        ])

        action_group.add_action(Gtk.Action("SortMenu", u"Сортування", None, None))

        action_group.add_radio_actions([
            ("SortByTime", None, u"Часу", "<control>Z", None, 1),
            ("SortByObjects", None, u"Об’єктами", "<control>X", None, 2),
            ("SortByAvgProbability", None, u"Ймовірністю", "<control>C", None, 3)
        ], 1, self.on_sort_menu_type_changed)

        action_group.add_radio_actions([
            ("SortRadioAscending", None, u"Від меншого до більшого", "<control>N", None, 1),
            ("SortRadioDescending", None, u"Від більшого до меншого", "<control>M", None, 2)
        ], 1, self.on_sort_menu_order_changed)

        action_group.add_actions([
            ("ProcessingMenu", None, u"Статус обробки", "<control>P", u"Статус обробки",
             lambda m: self.status_widgets.show_status()),
            # ("AdvancedSettingsMenu", None, u"Розширені налаштування", None, u"Розширені налаштування",
            #  lambda m: self.pass_me())
        ])

    def get_dframe_by_second(self, second):

        return self.detected_frames.get(second, None)

    def add_context_menu_actions(self, action_group):

        action_group.add_actions([
            #("EditMenu", None, "Edit"),
            ("ContextOpenImage", Gtk.STOCK_COPY, u"Відкрити", None, None,
             lambda b: self.context_menu_process(image=True)),
            ("ContextOpenFolder", Gtk.STOCK_PASTE, u"Відкрити в папці", None, None,
             lambda b: self.context_menu_process(folder=True)),
            ("ContextOpenVideo", None, u"Відкрити у VLC", "<control><alt>S", None,
             lambda b: self.context_menu_process(video=True)),
            ("ContextSave", None, u"Зберегти", None, None,
             lambda b: self.context_menu_process(save=True)),
        ])

    def context_menu_process(self, image=False, folder=False, video=False, save=False):

        frame_obj = self.get_listbox_selected_dframe()

        if not frame_obj:
            return

        if image:
            command = "eog -f %s" % frame_obj.frame_path
            subprocess.Popen(command.split(), stdout=subprocess.PIPE)

        if folder:
            command = "nautilus %s" % frame_obj.frame_path
            subprocess.Popen(command.split(), stdout=subprocess.PIPE)

        if video:
            command = "vlc %s --video-filter magnify --start-time=%d --rate=%f" % \
                      (self.video_path, frame_obj.second-1, 0.7)# --bookmarks=
            subprocess.Popen(command.split(), stdout=subprocess.PIPE)

        if save:
            file_path = self.get_save_file_dialog(second=frame_obj.second)
            if file_path:
                if not file_path.lower().endswith('.png'):
                    file_path += ".png"
                frame_obj.cairo_image.write_to_png(file_path)

    def get_listbox_selected_dframe(self):

        selected = self.listbox_thumbnails.get_selected_row()
        if selected:
            try:
                children1 = selected.get_child().get_children()[0].get_children()[1].get_children()
                time = int(time_to_seconds(children1[0].get_text()))
                return self.detected_frames.get(time, None)
            except AttributeError, e:
                pass
        return None

    def hide_selected(self):

        for second, dframe in self.detected_frames.items():

            if self.visibility_flag:
                if not dframe.da_visible:
                    dframe.da.hide()
            else:
                if not dframe.da_visible:
                    dframe.da.show()

        self.visibility_flag = not self.visibility_flag

    def on_sort_menu_type_changed(self, widget, current):

        selected = current.get_current_value()
        if selected:
            if selected == 1:  # Time
                self.listbox_thumbnails.set_sort_func(self.sorting_by_time_default)
                self.current_sort_func = self.sorting_by_time_default
            elif selected == 2:  # Objects
                self.listbox_thumbnails.set_sort_func(self.sorting_by_objects)
                self.current_sort_func = self.sorting_by_objects
            elif selected == 3:  # Probabbility
                print("\nSorting by probability - Not implemented yet")
                pass

    def on_sort_menu_order_changed(self, widget, current):

        selected = current.get_current_value()
        if selected:
            if selected == 1:  # Ascending
                self.sort_order_ascending = True
                self.sort_cb = sorting_callbacks['ascending']
            elif selected == 2:  # Descending
                self.sort_order_ascending = False
                self.sort_cb = sorting_callbacks['descending']

            self.listbox_thumbnails.set_sort_func(self.current_sort_func)

    def filter_widgets_adjust(self):

        self.filter_widgets.button_filter.connect("clicked", lambda b: self.get_and_set_filters())
        self.filter_widgets.button_filters_clear.connect("clicked",
                                                         lambda b: self.listbox_thumbnails.set_filter_func(
                                                             self.clear_filters))

    def get_and_set_filters(self):


        time_min = time_to_seconds(self.filter_widgets.entry_time_min.get_text())
        time_max = time_to_seconds(self.filter_widgets.entry_time_max.get_text())

        if time_min is None or time_min > self.video_duration_sec:
            time_min = 0
        if time_max is None or time_max > self.video_duration_sec:
            time_max = self.video_duration_sec

        if time_max < time_min:
            time_max, time_min = time_min, time_max
        self.filter_widgets.entry_time_min.set_text(seconds_to_hms_str(time_min))
        self.filter_widgets.entry_time_max.set_text(seconds_to_hms_str(time_max))

        # if time_min is not None or time_max is not None:
        #     self.listbox_thumbnails.set_filter_func(lambda r: self.filter_by_time(r,
        #                                                                           min_time=time_min,
        #                                                                           max_time=time_max))

        raw_text_min = self.filter_widgets.entry_obj_min.get_text()
        num_objects_min = abs(int(raw_text_min)) if is_int(raw_text_min) else None

        raw_text_max = self.filter_widgets.entry_obj_max.get_text()
        num_objects_max = abs(int(raw_text_max)) if is_int(raw_text_max) else None

        if num_objects_min is None or num_objects_min > self.max_frame_objects:
            num_objects_min = 0
        if num_objects_max is None or num_objects_max > self.max_frame_objects:
            num_objects_max = self.max_frame_objects

        if num_objects_max < num_objects_min:
            num_objects_max, num_objects_min = num_objects_min, num_objects_max
        self.filter_widgets.entry_obj_min.set_text(str(num_objects_min))
        self.filter_widgets.entry_obj_max.set_text(str(num_objects_max))

        # if num_objects_min is not None or num_objects_max is not None:
        #     self.listbox_thumbnails.set_filter_func(lambda r: self.filter_by_objects(r,
        #                                                                              min_objects=num_objects_min,
        #                                                                              max_objects=num_objects_max))
        self.listbox_thumbnails.set_filter_func(
            lambda r: self.filter_by_time_and_objects(r,
                                                      min_time=time_min,
                                                      max_time=time_max,
                                                      min_objects=num_objects_min,
                                                      max_objects=num_objects_max))

    @staticmethod
    def filter_by_time_and_objects(row,
                                   min_time=0, max_time=None,
                                   min_objects=0, max_objects=None):

        row_data = row.get_child().get_child().get_children()[1]

        row_raw_time = row_data.get_children()[0].get_text()
        row_time = time_to_seconds(row_raw_time)

        row_raw_obj = row_data.get_children()[2].get_text()
        row_objects = int(row_raw_obj) if is_int(row_raw_obj) else None

        if row_time is not None and row_objects is not None:
            if (max_time >= row_time >= min_time) and (max_objects >= row_objects >= min_objects):
                return True
        return False


    @staticmethod
    def filter_by_time(row, min_time=None, max_time=None):

        row_raw_time = row.get_child().get_child().get_children()[1].get_children()[0].get_text()
        row_time = time_to_seconds(row_raw_time)

        if row_time is not None:
            if min_time is not None and max_time is not None:
                if max_time >= row_time >= min_time:
                    return True
            elif min_time is not None and row_time >= min_time:
                return True
            elif max_time is not None and row_time <= max_time:
                return True
            return False
        return True

    @staticmethod
    def filter_by_objects(row, min_objects=None, max_objects=None):

        row_raw_obj = row.get_child().get_child().get_children()[1].get_children()[2].get_text()
        row_objects = int(row_raw_obj) if is_int(row_raw_obj) else None

        if row_objects is not None:
            if min_objects is not None and max_objects is not None:
                if max_objects >= row_objects >= min_objects:
                    return True
            elif min_objects is not None and row_objects >= min_objects:
                return True
            elif max_objects is not None and row_objects <= max_objects:
                return True
            return False
        return True

    def set_filters_values(self):
        self.filter_widgets.entry_time_min.set_text("00:00:00")
        self.filter_widgets.entry_time_max.set_text(seconds_to_hms_str(self.video_duration_sec))
        self.filter_widgets.entry_obj_min.set_text("0")
        self.filter_widgets.entry_obj_max.set_text(str(self.max_frame_objects))

    def clear_filters(self, row):

        self.set_filters_values()
        return True

    def settings_widgets_adjust(self):

        self.settings_widgets.label_res.set_text(self.results_dir_path)

        self.settings_widgets.entry_probability.set_text(str(self.min_probability))
        self.settings_widgets.button_video.connect("clicked", lambda b: self.get_open_file_dialog("video"))
        # self.settings_widgets.button_telemetry.connect("clicked", lambda b: self.get_open_file_dialog("telemetry"))
        self.settings_widgets.button_results.connect("clicked", lambda b: self.get_open_folder_dialog())
        self.settings_widgets.radio_order_chrono.connect("clicked",
                                                         lambda b: self.manage_radio_order_buttons(b, "chrono"))
        self.settings_widgets.radio_order_reverse.connect("clicked",
                                                          lambda b: self.manage_radio_order_buttons(b, "reverse"))
        self.settings_widgets.button_cancel.connect("clicked", lambda b: self.close_video())
        self.settings_widgets.button_process.connect("clicked",
                                                     lambda b: self.validate_and_process())

        # self.settings_widgets.entry_processing_start.connect("changed", lambda e: self.process_entry_time(e))
        # self.settings_widgets.entry_processing_end.connect("changed", lambda e: self.process_entry_time(e))
        # self.settings_widgets.entry_video_start.connect("changed", lambda e: self.process_entry_time(e))
        # self.settings_widgets.entry_telemetry_start.connect("changed", lambda e: self.process_entry_time(e))

    def validate_and_process(self, validate=True):

        print("\nVALIDATE and PROCESS\n")
        if validate:
            # check input values | if not validated
            start = time_to_seconds(self.settings_widgets.entry_processing_start.get_text())
            end = time_to_seconds(self.settings_widgets.entry_processing_end.get_text())

            if start and float(start) <= self.video_duration_sec-1:
                self.cut_from_sec = int(start)
            if end and float(end) <= self.video_duration_sec-1:
                self.cut_to_sec = int(end)

            probability = self.settings_widgets.entry_probability.get_text()

            if probability and is_float(probability) and 1 >= float(probability) >= 0:
                self.min_probability = float(probability)

            # results_dir = self.settings_widgets.label_res.get_text()
            # if os.path.isdir(results_dir):
            #     self.results_dir_path = results_dir

        if self.settings_widgets.window_visible:
            self.settings_widgets.hide_settings()

        if not self.video_path:
            self.get_open_file_dialog("video")

        print self.video_path
        print self.results_dir_path

        if not self.video_path:
            return

        # if not self.results_dir_path:
        #     self.get_open_folder_dialog()

        self.check_cut_detect_frames()

    def set_colours(self):

        pass
        #self.modify_bg(Gtk.StateType.NORMAL, white.to_color())
        # self.scrollable_window.modify_bg(Gtk.StateType.NORMAL, aloe.to_color())
        # self.hbox_thumbnails_sort.modify_bg(Gtk.StateType.NORMAL, black.to_color())
        # self._vbox_thumbnails.modify_bg(Gtk.StateType.NORMAL, green.to_color())

    def process_entry_time(self, widget):

        h = m = s = 0
        text = widget.get_text()
        print "\nText - " + text + "\n"

        if len(text) == 1:
            if not is_int(text):
                text = ""
        elif len(text) == 2:
            if not is_int(text):
                text = text[:-1]
        elif len(text) == 3:
            if text[-1] != ":":
                text = text[:-1] + ":"
        elif len(text) == 4:
            if not is_int(text[-1]):
                text = text[:-1]
        elif len(text) == 5:
            if not is_int(text[-2:]):
                text = text[:-1]
        elif len(text) == 6:
            if text[-1] != ":":
                text = text[:-1] + ":"
        elif len(text) == 7:
            if not is_int(text[-1]):
                text = text[:-1]
        elif len(text) == 8:
            if not is_int(text[-2:]):
                text = text[:-1]
            if text[2] != ":" or text[5] != ":":
                text = text[:2] + ":" + text[3:5] + ":" + text[-2:]

                #strptime

        widget.set_text(text)

    def get_combo_view(self):

        view_store = Gtk.ListStore(int, str)

        view_store.append([0, u"Відео і зображення"])
        #view_store.append([2, u"Відео і карта"])
        view_store.append([1, u"Відео"])
        view_store.append([2, u"Вигляд"])

        # cb = Gtk.ComboBox.new()
        # cb.set_model(view_store)
        #cb = Gtk.ComboBox.new_with_model_and_entry(view_store)
        cb = Gtk.ComboBox.new_with_model(view_store)

        # style = Gtk.rc_parse_string('''
        # style "my-style" { GtkComboBox::appears-as-list = 1 }
        # widget "*.mycombo" style "my-style"
        # ''')
        # cb.set_name('mycombo')
        # cb.set_style(style)

        #cb.set_style("appears-as-list")
        cb.connect("changed", self.on_combo_view_changed)
        renderer_text = Gtk.CellRendererText()
        cb.pack_start(renderer_text, True)
        cb.add_attribute(renderer_text, "text", 1)
        # cb.set_entry_text_column(1)
        cb.set_active(2)
        return cb

    def on_combo_view_changed(self, combo):

        tree_iter = combo.get_active_iter()
        if tree_iter is not None:
            model = combo.get_model()
            row_id, name = model[tree_iter][:2]
            if row_id == 1 or row_id == 2:
                self._vbox_thumbnails.hide()
                self.thumbnails_visible = False
            elif row_id == 0:
                self._vbox_thumbnails.show()
                self.thumbnails_visible = True
            else:
                print("\nSelected: ID=%d, name=%s  - Not implemented yet =)" % (row_id, name))

    def get_thumbnails_switch(self):

        switch_thumbnails = Gtk.Switch()
        switch_thumbnails.connect("notify::active", self.on_switch_activated)
        switch_thumbnails.set_size_request(127, 20)
        switch_thumbnails.set_margin_top(10)
        switch_thumbnails.set_margin_bottom(10)
        switch_thumbnails.set_valign(Gtk.Align.CENTER)
        return switch_thumbnails

    def get_player_control_toolbar(self):
        """Return a player control toolbar
        """

        tb = Gtk.Toolbar()
        # tb.set_style(Gtk.TOOLBAR_ICONS)

        for item, text, tooltip, stock, callback in (
                (Gtk.ToolButton, _("Play"), _("Play"), Gtk.STOCK_MEDIA_PLAY,
                 lambda b: self.check_and_play_video()),
                (Gtk.ToolButton, _("Pause"), _("Pause"), Gtk.STOCK_MEDIA_PAUSE,
                 lambda b: self.player.pause()),
                (Gtk.ToolButton, _("Stop"), _("Stop"), Gtk.STOCK_MEDIA_STOP,
                 lambda b: self.close_video()),
                (Gtk.SeparatorToolItem, None, None, None,
                 None),
                (Gtk.ToolButton, _("Previous"), _("Previous item"), Gtk.STOCK_GO_BACK,
                 lambda b: self.next_previous_frame(False)),
                (Gtk.ToolButton, _("Next"), _("Next item"), Gtk.STOCK_GO_FORWARD,
                 lambda b: self.next_previous_frame(True)),

                (Gtk.SeparatorToolItem, None, None, None,
                 None),
                # (Gtk.ToolButton, _("Snapshot"), _("Snapshot"), Gtk.STOCK_PRINT, lambda b: self.capture_frame()),
                # (Gtk.ToolButton, _("Open Folder"), _("Open Folder"), Gtk.STOCK_OPEN,
                #  lambda b: self.get_open_folder_dialog()),
                # (Gtk.ToolButton, _("Debug_py"), _("Debug py"), Gtk.STOCK_HELP,
                # lambda b: self.debug_py()),
                # (Gtk.ToolButton, _("Debug_ipdb"), _("Debug ipdb"), Gtk.STOCK_HELP,
                # lambda b: self.debug_ipdb()),
                # #
                # # (Gtk.SeparatorToolItem, None, None, None,
                # # None),
                # (Gtk.ToolButton, _("PROCESS"), _("PROCESS"), Gtk.STOCK_EXECUTE,
                #  lambda b: self.validate_and_process()),
        ):

            if item is Gtk.ToolButton:
                b = item(stock)
                b.set_tooltip_text(tooltip)
                b.connect("clicked", callback)
            else:
                b = item()
            tb.insert(b, -1)

        tb.show_all()
        return tb

    def resize_thumbnails(self):

        return
        for key, dframe in self.detected_frames.items():
            dframe.da.set_size_request(100, 100. / dframe.ratio)

    def sorting_by_time_default(self, row1, row2):

        children1 = row1.get_child().get_children()[0].get_children()[1].get_children()
        children2 = row2.get_child().get_children()[0].get_children()[1].get_children()

        time1, time2 = time_to_seconds(children1[0].get_text()), time_to_seconds(children2[0].get_text())

        if time1 < time2:
            return self.sort_cb['before']
        elif time1 > time2:
            return self.sort_cb['after']
        else:
            return 0

    def sorting_by_objects(self, row1, row2):

        children1 = row1.get_child().get_children()[0].get_children()[1].get_children()
        children2 = row2.get_child().get_children()[0].get_children()[1].get_children()

        num_objects1, num_objects2 = (int(children1[2].get_text()), int(children2[2].get_text()))
        if num_objects1 < num_objects2:
            return self.sort_cb['before']
        elif num_objects1 > num_objects2:
            return self.sort_cb['after']
        else:
            return 0

    def init_video_settings(self):

        for attr in self.init_video_attrs:
            setattr(self, attr, None)
        #import ipdb; ipdb.set_trace()
        self.allow_process_settings_window = True
        self.detection_completed = False
        self.main.main_window.set_title("UAV App")
        self.label_current_time.set_text("00:00:00")
        self.label_total_time.set_text("00:00:00")
        self.detection_time_to_end = None
        self.detection_progress = None
        self.status_widgets.on_video_upload()
        # self.settings_widgets.entry_results_dir.set_text(framesRootDirPath)
        # if self.results_file and hasattr(self.results_file, "closed") and not self.results_file.closed:
        #     self.results_file.close()
        #self.combo_view.set_active(2)

    def get_slider(self):

        slider = Gtk.HScale.new(self.slider_adj)

        # slider.configure(*s)
        # slider.set_size_request(400, 30)
        # slider.set_update_policy(Gtk.UPDATE_CONTINUOUS) DEPRECATED
        # slider.set_value_pos(Gtk.POS_RIGHT)

        slider.set_digits(0)
        slider.set_draw_value(False)
        return slider

    def update_slider(self):

        if self.player_visible:
            position = self.player.get_position()
            if 0 <= position <= 1:
                self.slider.set_value(position * 100)
                self.label_current_time.set_text(seconds_to_hms_str(self.position_to_second(position)))
            # else:
            #     self.label_current_time.set_text("00:00:00")
        return True

    def seek_slider_position(self, slider_adjustment):
        #print("%s" % str("on seek slider position"))
        value = slider_adjustment.get_value()
        if value and abs(value - self.slider_prev_position) > 0.5:
            self.player.set_position(value / 100.)
        #print "\n Value", self.position_to_second(value/100.)
        self.slider_prev_position = value

    def get_progressbar(self):

        progressbar = Gtk.ProgressBar()
        # self.progressbar.add_events(Gtk.Action.)
        # self.progressbar.set_discrete_blocks(5)
        # progressbar.set_size_request(400, 15)
        return progressbar

    def update_progressbar(self):

        position = self.player.get_position()
        if 0 <= position <= 1:
            #print time.time() - self.time
            self.progressbar.set_fraction(position)
        else:
            self.progressbar.set_pulse_step(0.05)
            self.progressbar.pulse()

        return True

    def manage_radio_order_buttons(self, widget, order):

        #label = widget.get_name()
        if order == "chrono":
            self.process_from_beginning = True
            self.radio_sort_order.set_current_value(1)
        if order == "reverse":
            self.process_from_beginning = False
            self.radio_sort_order.set_current_value(2)

    def process_probability_setting(self, widget, element):

        text = widget.get_text()
        prev_probability = element * 100

        if text:
            try:
                probability = float(text)
                print("\nProbability - %f\n" % probability)
            except ValueError, e:
                print("\nEXception - %s - %s\n" % (e, text) )
                probability = float(text[:-1])
            if probability < 1 or probability > 100:
                probability = prev_probability
                print("\nValue not in range | setting to %d\n" % probability)
            widget.set_text(str(probability))
            element = probability / 100.
            #print('\nProbability - &s\n' % self.window_settings.probability_entry.get_text())
        else:
            widget.set_text(str(prev_probability))

    def process(self, widget, data=None):
        print("\nProcessing\n")
        self.window_settings.hide()

    def show_hide_settings_window(self):

        if self.settings_widgets.window_visible:
            self.settings_widgets.hide_settings()
        else:
            self.settings_widgets.show_settings()

    def show_hide_thumbnails_listbox(self):

        if self.thumbnails_visible:
            self._vbox_thumbnails.hide()
            self.combo_view.set_active(1)
        else:
            self._vbox_thumbnails.show()
            self.combo_view.set_active(0)
        self.thumbnails_visible = not self.thumbnails_visible

    # CAFFE(DETECTION) FUNCTIONS
    @staticmethod
    def classify(inputs):
        predictions = classifier.predict(inputs, True)
        results = []
        for prediction in predictions:
            r = (None, None)
            for i, pred in enumerate(prediction):
                if pred > factor:
                    r = (i, pred)
                    break
            results.append(r)
        return results

    @staticmethod
    def find_kp(src_image):
        img = cv2.imread(src_image, 0)
        # orb = cv2.ORB()
        #return orb.detect(img, None)
        detector = cv2.ORB_create()
        #detector = cv2.FAST_create()
        #detector = cv2.MSER_create()
        #detector = cv2.BRISK_create()
        #detector = cv2.FREAK_create()
        return detector.detect(img)

    def detect_objects_caffe(self, frame_second, frame_path, results_file_path):

        print("\n\nDetecting objects on %d sec.\n\n" % frame_second)
        dframe = DFrame(frame_second, frame_path, self)
        image = caffe.io.load_image(frame_path, False)
        H, W = image.shape[:2]


        # self.results_file.write("%s\n" % str(frame_second))

        prects = defaultdict(float)
        points = []
        for k in self.find_kp(frame_path):
            points.append(k.pt)
            base_w = int(int(k.pt[0]) // self.ss) * self.ss
            base_h = int(int(k.pt[1]) // self.ss) * self.ss
            # print k.pt[0], k.pt[1], base_w, base_h
            for i_w in range(step):
                for i_h in range(step):
                    prects[(base_w - i_w * self.ss, base_h - i_h * self.ss)] += 1.

        tasks = []

        for w in range(0, W - self.size, self.size / step):
            for h in range(0, H - self.size, self.size / step):
                if prects[(w, h)] > 0:
                    tasks.append(( (w, h, self.size), image[h:h + self.size, w:w + self.size, :1]))

        print 'Created', len(tasks), ' tasks'

        chunks = [tasks[i:i + batch] for i in range(0, len(tasks), batch)]

        rects = []

        for c, chunk in enumerate(chunks):
            start_at = datetime.datetime.now()
            results = self.classify([task[1] for task in chunk])
            for i, result in enumerate(results):
                w, h, self.size = chunk[i][0]
                if result[0]:
                    rects.append((w, h, w + self.size, h + self.size, result[0], result[1]))

                    dobject = DObject('r', w, h, w + self.size, h + self.size, result[0], result[1])
                    if dobject.probability >= self.min_probability:
                        dframe.add_dobject(dobject)

            print ">> sys.stderr, Done chunk {}/{} in {}".format(c,
                                                                 len(chunks),
                                                                 datetime.datetime.now() - start_at) + " " + calc_mode

        if self.video_path:
            dframe.draw_dobjects()
            self.detected_frames[dframe.second] = dframe
            if dframe.len_dobjects > self.max_frame_objects:
                self.max_frame_objects = dframe.len_dobjects

        if self.save_res_to_file:

            with open(frame_path[:-3] + 'dtt', 'w') as fout,\
                    open(results_file_path, 'a+') as main_results_file:
                main_results_file.write(str(frame_second)+"\n")
                for point in points:
                    fout.write("p;" + ";".join(str(i) for i in point))
                    fout.write('\n')
                for rect in rects:
                    if len(rect) == 6 and rect[-1] >= self.min_probability:
                        main_results_file.write("\tr;%s\n" % ";".join(str(i) for i in rect))
                        #self.results_file.write("\tr;%s\n" % ";".join(str(i) for i in rect))
                        #self.results_file_path.seek(0)
                    fout.write("r;" + ";".join(str(i) for i in rect))
                    fout.write('\n')

    def close_video(self):

        self.player.stop()
        self.init_video_settings()
        self.player.set_position(0)
        self.slider.set_value(0)

        for key, dframe in self.detected_frames.items():
            self.listbox_thumbnails.remove(dframe.row)

        for tmp_image in self.tmp_images:
            os.remove(tmp_image)

        self.tmp_images = list()
        self.update_thumbnails_visibility(False)
        self.detected_frames = dict()
        self.settings_widgets.on_video_close()
        self.results_dir_path = framesRootDirPath
        self.settings_widgets.label_res.set_text(framesRootDirPath)
        #self.settings_widgets.entry_results_dir.set_text(framesRootDirPath)

    def play_pause_click(self, widget, event):
        self.player.pause()
        # if self.player.is_playing():
        # self.player.pause()
        # else:
        #     self.player.play()

    def get_scrollable_window(self):

        sw = Gtk.ScrolledWindow()
        sw.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        return sw

    def get_player_listbox(self):

        lb = Gtk.ListBox()
        lb.set_activate_on_single_click(True)
        # lb.modify_bg(Gtk.StateType.NORMAL, colors["blue"])
        # lb.set_property("activate-on-single-click", True)
        # lb.set_adjustment
        return lb

    def debug_py(self):
        if self.player.is_playing():
            self.player.pause()
        print("\n\nDebugging\n\n")
        self.player.play()

    def debug_ipdb(self):
        if self.player.is_playing():
            self.player.pause()
        import ipdb;

        ipdb.set_trace()
        self.player.play()

    def check_and_play_video(self):

        if not self.video_path:
            self.get_open_file_dialog("video")
        if self.video_path:
            self.player.play()

    def process_from_file(self):

        self.processing_flag = True
        with open(self.results_file_path, 'r') as self.results_file:

            dframe = DFrame(None, None, self)
            for line in self.results_file:
                if line.startswith("\t"):
                    stripped = line.strip().split(';')
                    try:
                        dobject = DObject(*stripped)
                        dframe.add_dobject(dobject)
                    except TypeError,e:
                        continue
                else:
                    if self.video_path \
                            and dframe.second is not None \
                            and dframe.frame_path \
                            and not dframe.added_to_listbox:
                        if dframe.second not in self.detected_frames.keys():
                            dframe.draw_dobjects()
                            self.detected_frames[dframe.second] = dframe
                            if dframe.len_dobjects > self.max_frame_objects:
                                self.max_frame_objects = dframe.len_dobjects

                    frame_second = int(line.strip())
                    dframe = DFrame(frame_second, None, self)
                    name = "Frame_at_%d_second.png" % frame_second
                    frame_path = os.path.join(self.results_dir_path, name)

                    while not os.path.isfile(frame_path):
                        self.capture_frame(path=frame_path, img_name=None, cut_time=frame_second,
                                           width=1280, height=720)
                        time.sleep(1)

                        # self.player.pause()
                    dframe.add_frame_path(frame_path)

            #if dframe.second is not None and dframe.frame_path and not dframe.added_to_listbox:
            if self.video_path \
                    and dframe.second is not None \
                    and dframe.frame_path \
                    and not dframe.added_to_listbox:
                if dframe.second not in self.detected_frames.keys():
                    dframe.draw_dobjects()
                    self.detected_frames[dframe.second] = dframe
                    if dframe.len_dobjects > self.max_frame_objects:
                        self.max_frame_objects = dframe.len_dobjects

        self.process_common(self.results_dir_path)

        self.processing_flag = False
        self.listbox_thumbnails.set_sort_func(self.sorting_by_time_default)
        self.on_detecting_end()

    def process_common(self, results_dir):

        print("PROCESSING COMMON")
        for index, frame_second in enumerate(self.frame_seconds):

            #print "dpr - %s, dp - %s" % (str(self.detection_pause_request), str(self.detection_paused))
            if not self.detection_paused:

                if frame_second in self.detected_frames:
                    continue

                init_time = time.time()
                name = "Frame_at_%d_second.png" % frame_second
                frame_path = os.path.join(results_dir, name)  # (self.results_sub_dir_path, name)
                # capture frame at second | IF NOT PRESENT IN RES DIR
                while not os.path.isfile(frame_path):
                    self.capture_frame(path=frame_path, img_name=None, cut_time=frame_second, width=1280,
                                       height=720)
                    time.sleep(1)
                # detect objects
                if os.path.isfile(frame_path):

                    # GLib.idle_add(self.detect_objects_caffe, frame_second, frame_path, self.results_file_path)
                    #self.processing_flag = True
                    print ("\t detect objects caffe in process common")
                    self.detect_objects_caffe(frame_second, frame_path, self.results_file_path)
                    #self.processing_flag = False

                seconds_per_frame = time.time() - init_time

                if self.frame_seconds:
                    print "Seconds per frame", int(seconds_per_frame)
                    print index, frame_second, self.frame_seconds
                    print "Frames remaining %d" % (len(self.frame_seconds) - index - 1)
                    self.detection_time_to_end = int(seconds_per_frame*1.2) * (len(self.frame_seconds) - index - 1)
                    self.detection_progress = (index + 1) * 100. / len(self.frame_seconds)
                    print ("Time remaining - %d" % self.detection_time_to_end)

                if self.detection_pause_request:
                    self.on_detecting_pause()

        if not self.detection_paused:
            print ("Process common - detction paused - false - detecting end - true")
            self.on_detecting_end()

    def resume_detecting(self):

        # if self.caffe_detecting_thread:
        #     self.status_widgets.label_status_message.set_text("Ще хвильку...")
        # else:
        # if not self.caffe_detecting_thread:
        if self.detection_paused:
            self.on_detecting_start()
            print("\n\t\tRESUMING DETECTION\n")
            self.thread = Thread(target=self.process_common, args=(self.results_sub_dir_path, ))
            #self.thread.daemon = True
            self.thread.start()
        else:
            print("\n\t\tNOT resuming detection\n")

    def check_cut_detect_frames(self):

        print("\t\t\tPROCESSING")
        ds = datetime.datetime.now()

        process_beginning = self.cut_from_sec if self.cut_from_sec is not None else 0
        process_end = self.cut_to_sec if self.cut_to_sec is not None else self.video_duration_sec

        if not self.process_from_beginning:
            process_beginning, process_end = process_end, process_beginning
            self.cut_step = - self.cut_step

        self.frame_seconds = range(process_beginning, process_end, self.cut_step)

        self.on_detecting_start()

        self.results_file_path = os.path.join(self.results_dir_path,
                                      self.video_name.split('.')[0] + "__objects.dtt")

        if os.path.isfile(self.results_file_path):

            print("\nPROCESSING FROM FILE\n")
            # IF IN THERE ARE RESULTS FILE IN RESULTS DIR | LOAD DETECTED DATA FROM FILE
            self.thread = Thread(target=self.process_from_file)
            #self.thread.daemon = True
            self.thread.start()
            print("\n\n\n READING TOOK - %d secs \n\n\n" % (datetime.datetime.now() - ds).total_seconds())

        else:

            print("\nGenerating default results subdirectory\n")
            self.results_sub_dir_path = os.path.join(self.results_dir_path,
                                                 self.video_name.split('.')[0] +
                                                 "__frames__%02d-%02d-%02d__%02d_%02d_%02d" % (
                                                     ds.year, ds.month, ds.day,
                                                     ds.hour, ds.minute, ds.second))

            check_and_create_dir(self.results_sub_dir_path)

            self.results_file_path = os.path.join(self.results_sub_dir_path,
                              self.video_name.split('.')[0] + "__objects.dtt")

            print("\nPROCESS COMMON selected\n")
            # NO RESULTS FILE | MAKE|LOAD SNAPSHOTS AND RUN DETECTION
            self.thread = Thread(target=self.process_common, args=(self.results_sub_dir_path,))
            #self.thread.daemon = True
            self.thread.start()


    def capture_frame(self, path=None, img_name=None, cut_time=None, fformat=".png", width=0, height=0):

        if path and os.path.isfile(path):
            return

        if not path:
            path = self.results_dir_path

        if cut_time is not None and self.video_duration_sec >= cut_time >= 0:
            # time to pos
            # if not img_name:
            #     img_name = "Frame_at_%d_sec__%s" % (time, self.video_name.split(".")[0])
            #print "Setting position ", cut_time
            self.player.set_position(self.second_to_position(cut_time))
            if self.player.is_playing():
                self.player.pause()
        else:
            now = datetime.datetime.now()
            img_name = "Snapshot_%s__%d-%d-%d_%d_%d_%d" % (self.video_name.split(".")[0], now.year, now.month, now.day,
                                                           now.hour, now.minute, now.second)
        #print "Current position ", self.position_to_second(self.player.get_position())
        snap = self.player.take_snapshot(save_to=path, name=img_name, snap_format=fformat,
                                         width=width, height=height)

        if self.player.is_playing():
            self.player.pause()


    def set_results_folder(self, dir_path):
        if os.path.isdir(dir_path):
            setattr(self, "results_dir_path", dir_path)
            #self.settings_widgets.entry_results_dir.set_text(dir_path)
            self.settings_widgets.label_res.set_text(dir_path)

    def get_open_folder_dialog(self):

        chooser = Gtk.FileChooserDialog(u"Оберіть папку для збереження результатів",
                                        action=Gtk.FileChooserAction.SELECT_FOLDER,  #FILE_CHOOSER_ACTION_SELECT_FOLDER,
                                        buttons=(u"Скасувати", Gtk.ResponseType.CANCEL,
                                                 u"Обрати", Gtk.ResponseType.OK))
        self.current_dialog = chooser
        chooser.set_default_response(Gtk.ResponseType.CANCEL)
        chooser.set_current_folder(framesRootDirPath)

        response = chooser.run()
        if response == Gtk.ResponseType.OK:
            dir_path = chooser.get_filename()

            self.set_results_folder(dir_path)

            chooser.destroy()
        #elif response == Gtk.ResponseType.CANCEL:
        else:
            print("\nYou've pressed Cancel.\n")
        chooser.hide()
        chooser.destroy()

    def get_save_file_dialog(self, filename=None, second=None, folder=None):

        chooser = Gtk.FileChooserDialog(u"Оберіть куди зберегти файл",
                                        action=Gtk.FileChooserAction.SAVE,
                                        buttons=(u"Скасувати", Gtk.ResponseType.CANCEL,
                                                 u"Зберегти", Gtk.ResponseType.OK))
        chooser.set_default_response(Gtk.ResponseType.CANCEL)
        extension = ".png"
        if folder and os.path.isdir(folder):
            chooser.set_current_folder(folder)
        else:
            chooser.set_current_folder(framesRootDirPath)

        if not filename:
            ds = datetime.datetime.now()
            filename = self.video_name.strip(".")[0] + "__Frame__"
            if second:
                filename += "at_%d_sec__" % second

            filename += "__%d-%d-%d__%d_%d_%d" % (ds.year, ds.month, ds.day, ds.hour, ds.minute, ds.second)
            filename += extension

        chooser.set_current_name(filename)

        response = chooser.run()
        if response == Gtk.ResponseType.OK:
            file_path = chooser.get_filename()
            chooser.destroy()
            return file_path
        else:
            print("\nYou've pressed Cancel.\n")
            chooser.hide()
            chooser.destroy()
        return None

    def open_file(self, file_type, file_path):

        if os.path.isfile(file_path):
            if file_type == "video":

                if self.video_path:
                    if self.video_path != file_path:
                        self.close_video()
                    else:
                        response = self.show_video_close_warning_dialog()
                        if response:
                            self.close_video()
                        else:
                            return

                self.player.set_media(instance.media_new(file_path))
                self.video_name = get_filename(file_path)
                self.main.main_window.set_title(self.video_name)

                self.player.play()
                if self.player.is_playing():
                    self.player.pause()

                while not self.video_size:
                    self.video_size = self.player.video_get_size()

                # if self.video_size:
                #     self._vlc_widget.set_size_request(*self.video_size)

                raw_length = self.player.get_length()
                while not raw_length or int(raw_length) <= 0:
                    self.player.pause()
                    raw_length = self.player.get_length()

                if self.player.is_playing():
                    self.player.pause()

                self.video_duration_sec = (raw_length / 1000)
                self.settings_widgets.on_video_open(file_path, self.video_duration_sec)
                self.label_total_time.set_text(seconds_to_hms_str(self.video_duration_sec))
                self.set_filters_values()

            elif file_type == "telemetry":
                self.window_settings.label_telem_path.set_text(file_path)
                # parse and pack telemetry

            if hasattr(self, file_type + "_path"):
                setattr(self, file_type + "_path", file_path)

    def close_file(self, file_type="video"):

        self.player.stop()
        self.init_video_settings()
        self.settings_widgets.on_video_close()
        # if file_type == "video":
        #     self.video_name = None
        #     self.video_duration_sec = None
        # elif file_type == "telemetry":
        #     pass
        #
        # if hasattr(self, file_type + "_path"):
        #     setattr(self, file_type + "_path", None)

    def get_open_file_dialog(self, file_type="video"):
        # telemetry and video open dialog

        chooser = Gtk.FileChooserDialog(u"Оберіть відео файл",  # % file_type.title(),
                                        action=Gtk.FileChooserAction.OPEN,
                                        buttons=(u"Скасувати", Gtk.ResponseType.CANCEL,
                                                 u"Відкрити", Gtk.ResponseType.OK))
        chooser.set_position(Gtk.WindowPosition.CENTER)
        chooser.set_default_response(Gtk.ResponseType.CANCEL)
        chooser.set_current_folder(homeDirectory)

        ffilter = Gtk.FileFilter()
        ffilter.set_name("%s File" % file_type.title())

        for extension in open_file_dialog_filters[file_type]:
            ffilter.add_pattern(extension)

        chooser.add_filter(ffilter)
        response = chooser.run()
        if response == Gtk.ResponseType.OK:
            filepath = chooser.get_filename()
            if os.path.isfile(filepath):
                self.open_file(file_type, filepath)

        elif response == Gtk.ResponseType.CANCEL:
            print 'Closed, no files selected'
        chooser.destroy()

    def position_to_second(self, position):
        if self.video_duration_sec:
            return float(position) * self.video_duration_sec

    def second_to_position(self, second):
        if self.video_duration_sec:
            return float(second) / self.video_duration_sec

    @staticmethod
    def pass_me():
        print ("PASSED")
        pass


class VideoPlayer:
    """Example simple video player.
    """

    def __init__(self):
        self.vlc = None  # DecoratedVLCWidget()
        self.main_window = None

    def exit(self):

        print("EXIT FUNC")
        if self.vlc:
            if self.vlc.allow_main_close:
                print("EXIT allowed")
                self.vlc.detection_paused = True
                self.vlc.on_detecting_end()
                self.vlc.close_video()
                self.vlc.status_widgets.main_window.destroy()
                self.vlc.settings_widgets.main_window.destroy()

                Gtk.main_quit()
                sys.exit(1)
            else:
                print("EXIT disallowed")
                self.vlc.show_player_close_warning_dialog()
        return True

    def main(self, fname=False):
        self.main_window = Gtk.Window()  # (Gtk.Window.TOPLEVEL)
        self.main_window.set_position(Gtk.WindowPosition.CENTER)
        self.main_window.set_size_request(800, 530)
        # w.set_policy(Gtk.FALSE, Gtk.FALSE, Gtk.FALSE)
        self.main_window.set_title("UAV App")
        self.main_window.set_name("main_window")

        self.vlc = DecoratedVLCWidget(self)

        if fname:
            self.vlc.player.set_media(instance.media_new(fname))

        self.main_window.add(self.vlc)

        self.main_window.show()

        self.main_window.connect("delete_event", lambda w, b: self.exit())
        self.main_window.connect("destroy", lambda w: self.exit())
        Gtk.main()


if __name__ == '__main__':

    len_inputs = len(sys.argv)
    if len_inputs == 1:
        p = VideoPlayer()
        p.main()
    elif len_inputs == 2:
        p = VideoPlayer()
        p.main(sys.argv[1])
        # elif len_inputs > 2:
        #     p = MultiVideoPlayer()
        #     p.main(sys.argv[1:])
