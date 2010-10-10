#!/usr/bin/python
# -*- coding: utf-8 -*-

"""
 Gestor de programas 1.1
 Copyright (C) 2010
 Author: Mario Colque <mario@tuquito.org.ar>
 Tuquito Team! - www.tuquito.org.ar

 This program is free software; you can redistribute it and/or modify
 it under the terms of the GNU General Public License as published by
 the Free Software Foundation; version 3 of the License.
 This program is distributed in the hope that it will be useful,
 but WITHOUT ANY WARRANTY; without even the implied warranty of
 MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
 GNU General Public License for more details.
 You should have received a copy of the GNU General Public License
 along with this program; if not, write to the Free Software
 Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA 02110-1301, USA.
"""

import Classes
import sys, os, commands
import gtk, gtk.glade
import gettext
import threading
import webkit
import string
import StringIO
import time
import ConfigParser
import apt
import urllib2
import aptdaemon
from aptdaemon.client import AptClient
from aptdaemon import enums
from subprocess import Popen, PIPE
from widgets.pathbar2 import NavigationBar
from widgets.searchentry import SearchEntry
from user import home
import base64

# i18n
gettext.install("tuquito-software-manager", "/usr/share/tuquito/locale")

# i18n for menu item
menuName = _("Software Manager")
menuComment = _("Install new applications")

architecture = commands.getoutput("uname -a")
if architecture.find("x86_64") >= 0:
	import ctypes
	libc = ctypes.CDLL('libc.so.6')
	libc.prctl(15, 'softwareManager', 0, 0, 0)
else:
	import dl
	libc = dl.open('/lib/libc.so.6')
	libc.call('prctl', 15, 'softwareManager', 0, 0, 0)

gtk.gdk.threads_init()

global shutdown_flag
shutdown_flag = False

class TransactionLoop(threading.Thread):
	def __init__(self, application, packages, wTree):
		threading.Thread.__init__(self)
		self.application = application
		self.wTree = wTree
		self.progressbar = wTree.get_widget("progressbar1")
		self.btn_trans = wTree.get_widget("button_transactions")
		self.tree_transactions = wTree.get_widget("tree_transactions")
		self.packages = packages
		self.apt_daemon = aptdaemon.client.get_aptdaemon()

	def run(self):
		try:
			from aptdaemon import client
			model = gtk.TreeStore(str, str, str, float, object)
			self.tree_transactions.set_model(model)
			self.tree_transactions.connect("button-release-event", self.menuPopup)

			global shutdown_flag
			while not shutdown_flag:
				try:
					time.sleep(1)
					#Get the list of active transactions
					current, pending = self.apt_daemon.GetActiveTransactions()
					num_transactions = 0
					sum_progress = 0
					tids = []
					for tid in [current] + pending:
						if not tid:
							continue
						tids.append(tid)
						num_transactions += 1
						transaction = client.get_transaction(tid, error_handler=lambda x: True)
						label = _("%s (running in the background)") % self.get_role_description(transaction)
						if "tuquito_label" in transaction.meta_data.keys():
							label = transaction.meta_data["tuquito_label"]

						sum_progress += transaction.progress

						transaction_is_new = True
						iter = model.get_iter_first()
						while iter is not None:
							if model.get_value(iter, 4).tid == transaction.tid:
								model.set_value(iter, 1, self.get_status_description(transaction))
								model.set_value(iter, 2, str(transaction.progress) + '%')
								model.set_value(iter, 3, transaction.progress)
								transaction_is_new = False
							iter = model.iter_next(iter)
						if transaction_is_new:
							iter = model.insert_before(None, None)
							model.set_value(iter, 0, label)
							model.set_value(iter, 1, self.get_status_description(transaction))
							model.set_value(iter, 2, str(transaction.progress) + '%')
							model.set_value(iter, 3, transaction.progress)
							model.set_value(iter, 4, transaction)

					#Remove transactions in the tree not found in the daemon
					iter = model.get_iter_first()
					while iter is not None:
						if model.get_value(iter, 4).tid not in tids:
							transaction = model.get_value(iter, 4)
							iter_to_be_removed = iter
							iter = model.iter_next(iter)
							model.remove(iter_to_be_removed)
							if "tuquito_pkgname" in transaction.meta_data.keys():
								pkg_name = transaction.meta_data["tuquito_pkgname"]
								cache = apt.Cache()
								new_pkg = cache[pkg_name]
								# Update packages
								for package in self.packages:
									if package.pkg.name == pkg_name:
										package.pkg = new_pkg
								# Update apps tree
								gtk.gdk.threads_enter()
								model_apps = self.wTree.get_widget("tree_applications").get_model()
								if isinstance(model_apps, gtk.TreeModelFilter):
									model_apps = model_apps.get_model()

								if model_apps is not None:
									iter_apps = model_apps.get_iter_first()
									while iter_apps is not None:
										package = model_apps.get_value(iter_apps, 3)
										if package.pkg.name == pkg_name:
											model_apps.set_value(iter_apps, 0, gtk.gdk.pixbuf_new_from_file_at_size(self.application.find_app_icon(package), 32, 32))
										iter_apps = model_apps.iter_next(iter_apps)
								gtk.gdk.threads_leave()
						else:
							iter = model.iter_next(iter)

					if num_transactions > 0:
						gtk.gdk.threads_enter()
						self.btn_trans.show()
						gtk.gdk.threads_leave()
						todo = 90 * num_transactions # because they only go to 90%
						fraction = float(sum_progress) / float(todo)
						if num_transactions > 1:
							progressText = _("%d ongoing actions") % num_transactions + ' - ' + str(int(fraction * 100)) + '%'
						else:
							progressText = _("%d ongoing action") % num_transactions + ' - ' + str(int(fraction * 100)) + '%'
					else:
						fraction = 0
						progressText = _("%d ongoing actions") % num_transactions
						gtk.gdk.threads_enter()
						self.btn_trans.hide()
						gtk.gdk.threads_leave()

					#Update
					gtk.gdk.threads_enter()
					self.progressbar.set_text(progressText)
					self.progressbar.set_fraction(fraction)
					gtk.gdk.threads_leave()
				except Exception, detail:
					print detail
					import traceback
					traceback.print_exc(file=sys.stdout)
					self.apt_daemon = aptdaemon.client.get_aptdaemon()
					print "A problem occured but the transaction loop was kept running"
			del model
			return
		except Exception, detail:
			print detail
			print "End of transaction loop..."

	def menuPopup(self, widget, event):
		if event.button == 3:
			model, iter = self.tree_transactions.get_selection().get_selected()
			if iter is not None:
				transaction = model.get_value(iter, 4)
				menu = gtk.Menu()
				cancelMenuItem = gtk.MenuItem(_("Cancel the task: %s") % model.get_value(iter, 0))
				cancelMenuItem.set_sensitive(transaction.cancellable)
				menu.append(cancelMenuItem)
				menu.show_all()
				cancelMenuItem.connect( "activate", self.cancelTask, transaction)
				menu.popup( None, None, None, event.button, event.time )

	def cancelTask(self, menu, transaction):
		transaction.cancel()

	def get_status_description(self, transaction):
		from aptdaemon.enums import *
		descriptions = {STATUS_SETTING_UP:_("Setting up"), STATUS_WAITING:_("Waiting"), STATUS_WAITING_MEDIUM:_("Waiting for medium"), STATUS_WAITING_CONFIG_FILE_PROMPT:_("Waiting for config file prompt"), STATUS_WAITING_LOCK:_("Waiting for lock"), STATUS_RUNNING:_("Running"), STATUS_LOADING_CACHE:_("Loading cache"), STATUS_DOWNLOADING:_("Downloading"), STATUS_COMMITTING:_("Committing"), STATUS_CLEANING_UP:_("Cleaning up"), STATUS_RESOLVING_DEP:_("Resolving dependencies"), STATUS_FINISHED:_("Finished"), STATUS_CANCELLING:_("Cancelling")}
		if transaction.status in descriptions.keys():
			return descriptions[transaction.status]
		else:
			return transaction.status
	'''def get_status_description(self, transaction):
		descriptions = (_("Setting up"),_("Waiting"), _("Waiting for medium"), _("Waiting for config file prompt"), _("Waiting for lock"), _("Running"), _("Loading cache"), _("Downloading"), _("Committing"), _("Cleaning up"), _("Resolving dependencies"), _("Finished"), _("Cancelling"))
		return descriptions[transaction.status]'''


	def get_role_description(self, transaction):
		from aptdaemon.enums import *
		roles = {ROLE_UNSET:_("No role set"), ROLE_INSTALL_PACKAGES:_("Installing package"), ROLE_INSTALL_FILE:_("Installing file"), ROLE_UPGRADE_PACKAGES:_("Upgrading package"), ROLE_UPGRADE_SYSTEM:_("Upgrading system"), ROLE_UPDATE_CACHE:_("Updating cache"), ROLE_REMOVE_PACKAGES:_("Removing package"), ROLE_COMMIT_PACKAGES:_("Committing package"), ROLE_ADD_VENDOR_KEY_FILE:_("Adding vendor key file"), ROLE_REMOVE_VENDOR_KEY:_("Removing vendor key"), ROLE_ADD_REPOSITORY: _("Adding repository"), ROLE_ADD_VENDOR_KEY_FROM_KEYSERVER: _("Adding vendor key from keyserver"), ROLE_ENABLE_DISTRO_COMP: _("Enabling distribution component"), ROLE_FIX_BROKEN_DEPENDS: _("Fixing broken dependencies"), ROLE_FIX_INCOMPLETE_INSTALL: _("Fixing incomplete installations")}
		if transaction.role in roles.keys():
			return roles[transaction.role]
		else:
			return transaction.role
	'''def get_role_description(self, transaction):
		roles = (_("No role set"), _("Installing package"), _("Installing file"), _("Upgrading package"), _("Upgrading system"), _("Updating cache"), _("Removing package"), _("Committing package"), _("Adding vendor key file"), _("Removing vendor key"))
		return roles[transaction.role]'''

class Category:
	def __init__(self, name, icon, sections, parent, categories):
		self.name = name
		self.icon = icon
		self.parent = parent
		self.subcategories = []
		self.packages = []
		self.sections = sections
		self.matchingPackages = []
		if parent is not None:
			parent.subcategories.append(self)
		categories.append(self)
		cat = self
		while cat.parent is not None:
			cat = cat.parent

class Package:
	def __init__(self, name, pkg):
		self.name = name
		self.pkg = pkg
		self.categories = []

class Application():
	PAGE_CATEGORIES = 0
	PAGE_MIXED = 1
	PAGE_PACKAGES = 2
	PAGE_DETAILS = 3
	PAGE_SCREENSHOT = 4
	PAGE_WEBSITE = 5
	PAGE_SEARCH = 6
	PAGE_TRANSACTIONS = 7

	NAVIGATION_HOME = 1
	NAVIGATION_SEARCH = 2
	NAVIGATION_CATEGORY = 3
	NAVIGATION_SUB_CATEGORY = 4
	NAVIGATION_ITEM = 5
	NAVIGATION_SCREENSHOT = 6
	NAVIGATION_WEBSITE = 6

	def __init__(self):
		self.aptd_client = AptClient()

		self.add_categories()
		self.build_matched_packages()
		self.add_packages()

		# Build the GUI
		gladefile = "/usr/lib/tuquito/tuquito-software-manager/tuquito-software-manager.glade"
		wTree = gtk.glade.XML(gladefile, "main_window")
		wTree.get_widget("main_window").set_title(_("Software Manager"))
		wTree.get_widget("main_window").set_icon_from_file("/usr/lib/tuquito/tuquito-software-manager/logo.svg")
		wTree.get_widget("main_window").connect("delete_event", self.close_application)

		#self.transaction_loop = TransactionLoop(self.packages, wTree)
		self.transaction_loop = TransactionLoop(self, self.packages, wTree)
		self.transaction_loop.setDaemon(True)
		self.transaction_loop.start()

		self.prefs = self.read_configuration()

		# Build the menu
		fileMenu = gtk.MenuItem(_("_File"))
		fileSubmenu = gtk.Menu()
		fileMenu.set_submenu(fileSubmenu)
		closeMenuItem = gtk.ImageMenuItem(gtk.STOCK_CLOSE)
		closeMenuItem.get_child().set_text(_("Close"))
		closeMenuItem.connect("activate", self.close_application)
		fileSubmenu.append(closeMenuItem)

		editMenu = gtk.MenuItem(_("_Edit"))
		editSubmenu = gtk.Menu()
		editMenu.set_submenu(editSubmenu)
		prefsMenuItem = gtk.ImageMenuItem(gtk.STOCK_PREFERENCES)
		prefsMenuItem.get_child().set_text(_("Preferences"))
		prefsMenu = gtk.Menu()
		prefsMenuItem.set_submenu(prefsMenu)

		searchInSummaryMenuItem = gtk.CheckMenuItem(_("Search in packages summary (slower search)"))
		searchInSummaryMenuItem.set_active(self.prefs["search_in_summary"])
		searchInSummaryMenuItem.connect("toggled", self.set_search_filter, "search_in_summary")

		searchInDescriptionMenuItem = gtk.CheckMenuItem(_("Search in packages description (even slower search)"))
		searchInDescriptionMenuItem.set_active(self.prefs["search_in_description"])
		searchInDescriptionMenuItem.connect("toggled", self.set_search_filter, "search_in_description")

		openLinkExternalMenuItem = gtk.CheckMenuItem(_("Open links using the web browser"))
		openLinkExternalMenuItem.set_active(self.prefs["external_browser"])
		openLinkExternalMenuItem.connect("toggled", self.set_external_browser)

		prefsMenu.append(searchInSummaryMenuItem)
		prefsMenu.append(searchInDescriptionMenuItem)
		prefsMenu.append(openLinkExternalMenuItem)

		editSubmenu.append(prefsMenuItem)

		accountMenuItem = gtk.ImageMenuItem(gtk.STOCK_PREFERENCES)
		accountMenuItem.get_child().set_text(_("Account information"))
		accountMenuItem.connect("activate", self.open_account_info)
		editSubmenu.append(accountMenuItem)

		if os.path.exists("/usr/bin/software-properties-gtk") or os.path.exists("/usr/bin/software-properties-kde"):
			sourcesMenuItem = gtk.ImageMenuItem(gtk.STOCK_PREFERENCES)
			sourcesMenuItem.set_image(gtk.image_new_from_file("/usr/lib/tuquito/tuquito-software-manager/data/software-properties.png"))
			sourcesMenuItem.get_child().set_text(_("Software sources"))
			sourcesMenuItem.connect("activate", self.open_repositories)
			editSubmenu.append(sourcesMenuItem)

		viewMenu = gtk.MenuItem(_("_View"))
		viewSubmenu = gtk.Menu()
		viewMenu.set_submenu(viewSubmenu)

		availablePackagesMenuItem = gtk.CheckMenuItem(_("Available packages"))
		availablePackagesMenuItem.set_active(self.prefs["available_packages_visible"])
		availablePackagesMenuItem.connect("toggled", self.set_filter, "available_packages_visible")

		installedPackagesMenuItem = gtk.CheckMenuItem(_("Installed packages"))
		installedPackagesMenuItem.set_active(self.prefs["installed_packages_visible"])
		installedPackagesMenuItem.connect("toggled", self.set_filter, "installed_packages_visible")

		viewSubmenu.append(availablePackagesMenuItem)
		viewSubmenu.append(installedPackagesMenuItem)

		helpMenu = gtk.MenuItem(_("_Help"))
		helpSubmenu = gtk.Menu()
		helpMenu.set_submenu(helpSubmenu)
		aboutMenuItem = gtk.ImageMenuItem(gtk.STOCK_ABOUT)
		aboutMenuItem.get_child().set_text(_("About"))
		aboutMenuItem.connect("activate", self.open_about)
		helpSubmenu.append(aboutMenuItem)

		#browser.connect("activate", browser_callback)
		#browser.show()
		wTree.get_widget("menubar1").append(fileMenu)
		wTree.get_widget("menubar1").append(editMenu)
		wTree.get_widget("menubar1").append(viewMenu)
		wTree.get_widget("menubar1").append(helpMenu)

		# Build the applications tables
		self.tree_applications = wTree.get_widget("tree_applications")
#		self.tree_mixed_applications = wTree.get_widget("tree_mixed_applications")
		self.tree_search = wTree.get_widget("tree_search")
		self.tree_transactions = wTree.get_widget("tree_transactions")

		self.build_application_tree(self.tree_applications)
#		self.build_application_tree(self.tree_mixed_applications)
		self.build_application_tree(self.tree_search)
		self.build_transactions_tree(self.tree_transactions)

		self.navigation_bar = NavigationBar()
		self.searchentry = SearchEntry()
		self.searchentry.connect("terms-changed", self.on_search_terms_changed)
		top_hbox = gtk.HBox()
		top_hbox.pack_start(self.navigation_bar, padding=6)
		top_hbox.pack_start(self.searchentry, expand=False, padding=6)
		wTree.get_widget("toolbar").pack_start(top_hbox, expand=False, padding=6)

		self.notebook = wTree.get_widget("notebook1")

		# Build the category browsers
		self.browser = webkit.WebView()
		template = open("/usr/lib/tuquito/tuquito-software-manager/data/templates/CategoriesView.html").read()
		subs = {'header': _("Categories")}
		subs['select'] = _("Select a category...")
		html = string.Template(template).safe_substitute(subs)
		self.browser.load_html_string(html, "file:/")
		self.browser.connect("load-finished", self._on_load_finished)
	 	self.browser.connect('title-changed', self._on_title_changed)
		wTree.get_widget("scrolled_categories").add(self.browser)

		self.browser2 = webkit.WebView()
		template = open("/usr/lib/tuquito/tuquito-software-manager/data/templates/CategoriesView.html").read()
		subs = {'header': _("Categories")}
		subs['select'] = _("Select a category...")
		html = string.Template(template).safe_substitute(subs)
		self.browser2.load_html_string(html, "file:/")
	 	self.browser2.connect('title-changed', self._on_title_changed)
		wTree.get_widget("scrolled_mixed_categories").add(self.browser2)

		self.packageBrowser = webkit.WebView()
		wTree.get_widget("scrolled_details").add(self.packageBrowser)

		self.packageBrowser.connect('title-changed', self._on_title_changed)

		self.screenshotBrowser = webkit.WebView()
		wTree.get_widget("scrolled_screenshot").add(self.screenshotBrowser)

		self.websiteBrowser = webkit.WebView()
		wTree.get_widget("scrolled_website").add(self.websiteBrowser)

		# kill right click menus in webkit views
	        self.browser.connect("button-press-event", lambda w, e: e.button == 3)
		self.browser2.connect("button-press-event", lambda w, e: e.button == 3)
		self.packageBrowser.connect("button-press-event", lambda w, e: e.button == 3)
		self.screenshotBrowser.connect("button-press-event", lambda w, e: e.button == 3)

		wTree.get_widget("label_transactions_header").set_text(_("Active tasks:"))
		wTree.get_widget("progressbar1").hide_all()

		wTree.get_widget("button_transactions").connect("clicked", self.show_transactions)

		wTree.get_widget("main_window").show_all()
		wTree.get_widget("button_transactions").hide()

	def on_search_terms_changed(self, searchentry, terms):
		if terms != "":
			self.show_search_results(terms)

	def set_filter(self, checkmenuitem, configName):
		config = ConfigParser.ConfigParser()
		config.add_section("filter")
		if configName == "available_packages_visible":
			config.set("filter", "installed_packages_visible", self.prefs["installed_packages_visible"])
		else:
			config.set("filter", "available_packages_visible", self.prefs["available_packages_visible"])
		config.set("filter", configName, checkmenuitem.get_active())
		config.add_section("search")
		config.set("search", "search_in_summary", self.prefs["search_in_summary"])
		config.set("search", "search_in_description", self.prefs["search_in_description"])
		config.add_section("general")
		config.set("general", "external_browser", self.prefs["external_browser"])
		config.write(open(home + "/.tuquito/tuquito-software-manager/tuquito-software-manager.conf", 'w'))
		self.prefs = self.read_configuration()
		if self.model_filter is not None:
			self.model_filter.refilter()

	def set_search_filter(self, checkmenuitem, configName):
		config = ConfigParser.ConfigParser()
		config.add_section("search")
		if configName == "search_in_description":
			config.set("search", "search_in_summary", self.prefs["search_in_summary"])
		else:
			config.set("search", "search_in_description", self.prefs["search_in_description"])
		config.set("search", configName, checkmenuitem.get_active())
		config.add_section("filter")
		config.set("filter", "available_packages_visible", self.prefs["available_packages_visible"])
		config.set("filter", "installed_packages_visible", self.prefs["installed_packages_visible"])
		config.add_section("general")
		config.set("general", "external_browser", self.prefs["external_browser"])
		config.write(open(home + "/.tuquito/tuquito-software-manager/tuquito-software-manager.conf", 'w'))
		self.prefs = self.read_configuration()
		if self.searchentry.get_text() != "":
			self.show_search_results(self.searchentry.get_text())

	def set_external_browser(self, checkmenuitem):
		config = ConfigParser.ConfigParser()
		config.add_section("general")
		config.set("general", "external_browser", checkmenuitem.get_active())
		config.add_section("filter")
		config.set("filter", "available_packages_visible", self.prefs["available_packages_visible"])
		config.set("filter", "installed_packages_visible", self.prefs["installed_packages_visible"])
		config.add_section("search")
		config.set("search", "search_in_summary", self.prefs["search_in_summary"])
		config.set("search", "search_in_description", self.prefs["search_in_description"])
		config.write(open(home + "/.tuquito/tuquito-software-manager/tuquito-software-manager.conf", 'w'))
		self.prefs = self.read_configuration()

	def read_configuration(self, conf=None):
		# Lee la configuración
		config = ConfigParser.ConfigParser()
		config.read(home + "/.tuquito/tuquito-software-manager/account.conf")
		prefs = {}
		#Read account info
		try:
			prefs["username"] = config.get('account', 'username')
			prefs["password"] = config.get('account', 'password')
		except:
			prefs["username"] = ""
			prefs["password"] = ""

		config = ConfigParser.ConfigParser()
		config.read(home + "/.tuquito/tuquito-software-manager/tuquito-software-manager.conf")
		#Read filter info
		try:
			prefs["available_packages_visible"] = config.getboolean("filter", "available_packages_visible")
		except:
			prefs["available_packages_visible"] = True
		try:
			prefs["installed_packages_visible"] = config.getboolean("filter", "installed_packages_visible")
		except:
			prefs["installed_packages_visible"] = True

		#Read search info
		try:
			prefs["search_in_summary"] = config.getboolean("search", "search_in_summary")
		except:
			prefs["search_in_summary"] = False
		try:
			prefs["search_in_description"] = config.getboolean("search", "search_in_description")
		except:
			prefs["search_in_description"] = False

		#External browser
		try:
			prefs["external_browser"] = config.getboolean("general", "external_browser")
		except:
			prefs["external_browser"] = False
		return prefs

	def open_repositories(self, widget):
		if os.path.exists("/usr/bin/software-properties-gtk"):
			os.system("gksu /usr/bin/software-properties-gtk -D '%s'" % _("Software sources"))
		else:
			os.system("gksu /usr/bin/software-properties-kde -D '%s'" % _("Software sources"))
		self.close_application(None, None, 9) # Status code 9 means we want to restart ourselves

	def close_window(self, widget, window):
		window.hide()

	def open_account_info(self, widget):
		gladefile = "/usr/lib/tuquito/tuquito-software-manager/tuquito-software-manager.glade"
		wTree = gtk.glade.XML(gladefile, "window_account")
		wTree.get_widget("window_account").set_title(_("Account information"))
		wTree.get_widget("label1").set_label("<b>%s</b>" % _("Your community account"))
		wTree.get_widget("label1").set_use_markup(True)
		wTree.get_widget("label2").set_label("<i><small>%s</small></i>" % _("Enter your account info to post comments"))
		wTree.get_widget("label2").set_use_markup(True)
		wTree.get_widget("label3").set_label(_("Username:"))
		wTree.get_widget("label4").set_label(_("Password:"))
		wTree.get_widget("entry_username").set_text(self.prefs["username"])
		wTree.get_widget("entry_password").set_text(base64.b64decode(self.prefs["password"]))
		wTree.get_widget("close_button").connect("clicked", self.close_window, wTree.get_widget("window_account"))
		wTree.get_widget("save_button").connect("clicked", self.update_account_info, wTree)
		wTree.get_widget("window_account").show_all()

	def close_window(self, widget, window):
		window.hide()

	def update_account_info(self, widteg, data=None):
		config = ConfigParser.ConfigParser()
		config.add_section("account")
		username = data.get_widget("entry_username").get_text()
		password = base64.b64encode(data.get_widget("entry_password").get_text())
		config.set("account", "username", username)
		config.set("account", "password", password)
		config.write(open(home + "/.tuquito/tuquito-software-manager/account.conf", 'w'))
		self.prefs = self.read_configuration()
		data.get_widget("window_account").hide()

	def open_about(self, widget):
		os.system('/usr/lib/tuquito/tuquito-software-manager/about.py &')

	def show_transactions(self, widget):
		self.notebook.set_current_page(self.PAGE_TRANSACTIONS)

	def close_window(self, widget, window, extra=None):
		try:
			window.hide_all()
		except:
			pass

	def build_application_tree(self, treeview):
		column0 = gtk.TreeViewColumn(_("Icon"), gtk.CellRendererPixbuf(), pixbuf=0)
		column0.set_sort_column_id(0)
		column0.set_resizable(True)

		column1 = gtk.TreeViewColumn(_("Application"), gtk.CellRendererText(), markup=1)
		column1.set_sort_column_id(1)
		column1.set_resizable(True)
		column1.set_sizing(gtk.TREE_VIEW_COLUMN_FIXED)
		column1.set_min_width(350)
		column1.set_max_width(350)

		treeview.append_column(column0)
		treeview.append_column(column1)
		treeview.set_headers_visible(False)
		treeview.show()

		selection = treeview.get_selection()
		selection.set_mode(gtk.SELECTION_SINGLE)
		selection.connect("changed", self.show_selected)

	def build_transactions_tree(self, treeview):
		column0 = gtk.TreeViewColumn(_("Task"), gtk.CellRendererText(), text=0)
		column0.set_resizable(True)

		column1 = gtk.TreeViewColumn(_("Status"), gtk.CellRendererText(), text=1)
		column1.set_resizable(True)

		column2 = gtk.TreeViewColumn(_("Progress"), gtk.CellRendererProgress(), text=2, value=3)
		column2.set_resizable(True)

		treeview.append_column(column0)
		treeview.append_column(column1)
		treeview.append_column(column2)
		treeview.set_headers_visible(True)
		treeview.show()

	def show_selected(self, selection):
		(model, iter) = selection.get_selected()
		if iter != None:
			self.selected_package = model.get_value(iter, 3)
			self.show_package(self.selected_package)
			selection.unselect_all()

	def navigate(self, button, destination):
		if destination == "search":
			self.notebook.set_current_page(self.PAGE_SEARCH)
		else:
			self.searchentry.set_text("")
			if isinstance(destination, Category):
				if len(destination.subcategories) > 0:
					if len(destination.packages) > 0:
						self.notebook.set_current_page(self.PAGE_MIXED)
					else:
						self.notebook.set_current_page(self.PAGE_CATEGORIES)
				else:
					self.notebook.set_current_page(self.PAGE_PACKAGES)
			elif isinstance(destination, Package):
				self.notebook.set_current_page(self.PAGE_DETAILS)
			elif destination == "screenshot":
				self.notebook.set_current_page(self.PAGE_SCREENSHOT)
			else:
				self.notebook.set_current_page(self.PAGE_WEBSITE)

	def close_application(self, window, event=None, exit_code=0):
		global shutdown_flag
		shutdown_flag = True
		gtk.main_quit()
		sys.exit(exit_code)

	def _on_load_finished(self, view, frame):
		# Get the categories
		self.show_category(self.root_category)

	def on_category_clicked(self, name):
		for category in self.categories:
		    if category.name == name:
			self.show_category(category)

	def on_button_clicked(self):
		package = self.current_package
		if package is not None:
			if package.pkg.is_installed:
				os.system("/usr/lib/tuquito/tuquito-software-manager/aptd_client.py remove %s" % package.pkg.name)
			else:
				os.system("/usr/lib/tuquito/tuquito-software-manager/aptd_client.py install %s" % package.pkg.name)

	'''def on_button_clicked(self, data=None):
		package = self.current_package
		if package is not None and data is not None:
			action = LaunchAPTAction(self.aptd_client, package, data)
			action.start()'''

	def on_screenshot_clicked(self):
		package = self.current_package
		if package is not None:
			template = open("/usr/lib/tuquito/tuquito-software-manager/data/templates/ScreenshotView.html").read()
			subs = {}
			subs['appname'] = self.current_package.pkg.name
			html = string.Template(template).safe_substitute(subs)
			self.screenshotBrowser.load_html_string(html, "file:/")
			self.navigation_bar.add_with_id(_("Screenshot"), self.navigate, self.NAVIGATION_SCREENSHOT, "screenshot")

	def on_website_clicked(self):
		package = self.current_package
		if package != None:
			url = self.current_package.pkg.candidate.homepage
			if self.prefs['external_browser']:
				os.system("xdg-open " + url + " &")
			else:
				self.websiteBrowser.open(url)
				self.navigation_bar.add_with_id(_("Website"), self.navigate, self.NAVIGATION_WEBSITE, "website")

	def on_comment_clicked(self, package=None):
		if package != None:
			url = "http://www.tuquito.org.ar/software/comment.php?name=" + package + "&limit=false"
			self.websiteBrowser.open(url)
			self.navigation_bar.add_with_id(_("Comments"), self.navigate, self.NAVIGATION_WEBSITE, "website")

	def _on_title_changed(self, view, frame, title):
		# no op - needed to reset the title after a action so that
		#         the action can be triggered again
		if title.startswith("nop"):
		    return
		# call directive looks like:
		#  "call:func:arg1,arg2"
		#  "call:func"
		if title.startswith("call:"):
			args_str = ""
			args_list = []
		    # try long form (with arguments) first
			try:
				(t,funcname,args_str) = title.split(":")
			except ValueError:
				# now try short (without arguments)
				(t,funcname) = title.split(":")
			if args_str:
				args_list = args_str.split(",")
			# see if we have it and if it can be called
			f = getattr(self, funcname)
			if f and callable(f):
				f(*args_list)
			# now we need to reset the title
			self.browser.execute_script('document.title = "nop"')

	def add_categories(self):
		self.categories = []
		self.root_category = Category(_("Categories"), "applications-other", None, None, self.categories)
		featured = Category(_("Featured"), "gtk-about", None, self.root_category, self.categories)
		featured.matchingPackages = self.file_to_array("/usr/lib/tuquito/tuquito-software-manager/categories/featured.list")

		Category(_("Accessories"), "applications-utilities", ("accessories", "utils"), self.root_category, self.categories)

		subcat = Category(_("Access"), "access", None, self.root_category, self.categories)
		subcat.matchingPackages = self.file_to_array("/usr/lib/tuquito/tuquito-software-manager/categories/access.list")

		subcat = Category(_("Education"), "applications-accessories", ("education", "math"), self.root_category, self.categories)
		subcat.matchingPackages = self.file_to_array("/usr/lib/tuquito/tuquito-software-manager/categories/education.list")

		subcat = Category(_("Fonts"), "applications-fonts", None, self.root_category, self.categories)
		subcat.matchingPackages = self.file_to_array("/usr/lib/tuquito/tuquito-software-manager/categories/fonts.list")

		games = Category(_("Games"), "applications-games", ("games"), self.root_category, self.categories)

		subcat = Category(_("Board games"), "applications-games", None, games, self.categories)
		subcat.matchingPackages = self.file_to_array("/usr/lib/tuquito/tuquito-software-manager/categories/games-board.list")

		subcat = Category(_("First-person shooters"), "applications-games", None, games, self.categories)
		subcat.matchingPackages = self.file_to_array("/usr/lib/tuquito/tuquito-software-manager/categories/games-fps.list")

		subcat = Category(_("Real-time strategy"), "applications-games", None, games, self.categories)
		subcat.matchingPackages = self.file_to_array("/usr/lib/tuquito/tuquito-software-manager/categories/games-rts.list")

		subcat = Category(_("Turn-based strategy"), "applications-games", None, games, self.categories)
		subcat.matchingPackages = self.file_to_array("/usr/lib/tuquito/tuquito-software-manager/categories/games-tbs.list")

		subcat = Category(_("Emulators"), "applications-games", None, games, self.categories)
		subcat.matchingPackages = self.file_to_array("/usr/lib/tuquito/tuquito-software-manager/categories/games-emulators.list")

		subcat = Category(_("Simulation and racing"), "applications-games", None, games, self.categories)
		subcat.matchingPackages = self.file_to_array("/usr/lib/tuquito/tuquito-software-manager/categories/games-simulations.list")

		graphics = Category(_("Graphics"), "applications-graphics", ("graphics"), self.root_category, self.categories)
		graphics.matchingPackages = self.file_to_array("/usr/lib/tuquito/tuquito-software-manager/categories/graphics.list")

		subcat = Category(_("3D"), "applications-graphics", None, graphics, self.categories)
		subcat.matchingPackages = self.file_to_array("/usr/lib/tuquito/tuquito-software-manager/categories/graphics-3d.list")

		subcat = Category(_("Drawing"), "applications-graphics", None, graphics, self.categories)
		subcat.matchingPackages = self.file_to_array("/usr/lib/tuquito/tuquito-software-manager/categories/graphics-drawing.list")

		subcat = Category(_("Photography"), "applications-graphics", None, graphics, self.categories)
		subcat.matchingPackages = self.file_to_array("/usr/lib/tuquito/tuquito-software-manager/categories/graphics-photography.list")

		subcat = Category(_("Publishing"), "applications-graphics", None, graphics, self.categories)
		subcat.matchingPackages = self.file_to_array("/usr/lib/tuquito/tuquito-software-manager/categories/graphics-publishing.list")

		subcat = Category(_("Scanning"), "applications-graphics", None, graphics, self.categories)
		subcat.matchingPackages = self.file_to_array("/usr/lib/tuquito/tuquito-software-manager/categories/graphics-scanning.list")

		subcat = Category(_("Viewers"), "applications-graphics", None, graphics, self.categories)
		subcat.matchingPackages = self.file_to_array("/usr/lib/tuquito/tuquito-software-manager/categories/graphics-viewers.list")

		internet = Category(_("Internet"), "applications-internet", ("mail", "web", "net"), self.root_category, self.categories)

		subcat = Category(_("Web"), "applications-internet", None, internet, self.categories)
		subcat.matchingPackages = self.file_to_array("/usr/lib/tuquito/tuquito-software-manager/categories/internet-web.list")
		subcat = Category(_("Email"), "applications-internet", None, internet, self.categories)
		subcat.matchingPackages = self.file_to_array("/usr/lib/tuquito/tuquito-software-manager/categories/internet-email.list")
		subcat = Category(_("Chat"), "applications-internet", None, internet, self.categories)
		subcat.matchingPackages = self.file_to_array("/usr/lib/tuquito/tuquito-software-manager/categories/internet-chat.list")
		subcat = Category(_("File sharing"), "applications-internet", None, internet, self.categories)
		subcat.matchingPackages = self.file_to_array("/usr/lib/tuquito/tuquito-software-manager/categories/internet-filesharing.list")

		Category(_("Office"), "applications-office", ("office", "editors"), self.root_category, self.categories)
		Category(_("Science"), "applications-science", ("science", "math"), self.root_category, self.categories)

		cat = Category(_("Sound and video"), "applications-multimedia", ("multimedia", "video"), self.root_category, self.categories)
		cat.matchingPackages = self.file_to_array("/usr/lib/tuquito/tuquito-software-manager/categories/sound-video.list")

		subcat = Category(_("Themes and tweaks"), "preferences-other", None, self.root_category, self.categories)
		subcat.matchingPackages = self.file_to_array("/usr/lib/tuquito/tuquito-software-manager/categories/themes-tweaks.list")

		cat = Category(_("System tools"), "applications-system", ("system", "admin"), self.root_category, self.categories)
		cat.matchingPackages = self.file_to_array("/usr/lib/tuquito/tuquito-software-manager/categories/system-tools.list")

		Category(_("Programming"), "applications-development", ("devel"), self.root_category, self.categories)

		self.category_all = Category(_("Other"), "applications-other", None, self.root_category, self.categories)

	def file_to_array(self, filename):
		array = []
		f = open(filename)
		for line in f:
			line = line.replace("\n","").replace("\r","").strip();
			if line != "":
				array.append(line)
		return array

	def build_matched_packages(self):
		# Build a list of matched packages
		self.matchedPackages = []
		for category in self.categories:
			self.matchedPackages.extend(category.matchingPackages)
		self.matchedPackages.sort()

	def add_packages(self):
		self.packages = []
		self.packages_dict = {}
		cache = apt.Cache()
		for pkg in cache:
			package = Package(pkg.name, pkg)
			self.packages.append(package)
			self.packages_dict[pkg.name] = package
			self.category_all.packages.append(package)

			# If the package is not a "matching package", find categories with matching sections
			if pkg.name not in self.matchedPackages:
				section = pkg.section
				if "/" in section:
					section = section.split("/")[1]
				for category in self.categories:
					if category.sections is not None:
						if section in category.sections:
							category.packages.append(package)
							package.categories.append(category)

		# Process matching packages
		for category in self.categories:
			for package_name in category.matchingPackages:
				if package_name in self.packages_dict:
					package = self.packages_dict[package_name]
					category.packages.append(package)
					package.categories.append(category)

	def show_category(self, category):
		# Load subcategories
		if len(category.subcategories) > 0:
			if len(category.packages) == 0:
				# Show categories page
				browser = self.browser
			else:
				# Show mixed page
				browser = self.browser2

			theme = gtk.icon_theme_get_default()
			browser.execute_script('clearCategories()')
			for cat in category.subcategories:
				icon = None
				if theme.has_icon(cat.icon):
					iconInfo = theme.lookup_icon(cat.icon, 42, 0)
					if iconInfo and os.path.exists(iconInfo.get_filename()):
						icon = iconInfo.get_filename()
				if icon == None:
					iconInfo = theme.lookup_icon("applications-other", 42, 0)
					if iconInfo and os.path.exists(iconInfo.get_filename()):
						icon = iconInfo.get_filename()
				browser.execute_script('addCategory("%s", "%s", "%s")' % (cat.name, _("%d packages") % len(cat.packages), icon))
			browser.execute_script('animateItems()')

		# Load packages into self.tree_applications
		tree_applications = self.tree_applications
		model_applications = gtk.TreeStore(gtk.gdk.Pixbuf, str, gtk.gdk.Pixbuf, object)

		self.model_filter = model_applications.filter_new()
		self.model_filter.set_visible_func(self.visible_func)

		category.packages.sort()
		for package in category.packages[0:500]:
			iter = model_applications.insert_before(None, None)
			if package.pkg.is_installed:
				model_applications.set_value(iter, 0, gtk.gdk.pixbuf_new_from_file("/usr/lib/tuquito/tuquito-software-manager/data/installed.png"))
			else:
				model_applications.set_value(iter, 0, gtk.gdk.pixbuf_new_from_file("/usr/lib/tuquito/tuquito-software-manager/data/available.png"))

			summary = ""
			if package.pkg.candidate is not None:
				summary = package.pkg.candidate.summary
				summary = unicode(summary, 'UTF-8', 'replace')
				summary = summary.replace("<", "&lt;")
				summary = summary.replace("&", "&amp;")

			model_applications.set_value(iter, 1, "%s\n<small><span foreground='#555555'>%s</span></small>" % (package.name, summary.capitalize()))

			model_applications.set_value(iter, 3, package)

		tree_applications.set_model(self.model_filter)
		first = model_applications.get_iter_first()
		del model_applications

		# Update the navigation bar
		if category == self.root_category:
			self.navigation_bar.add_with_id(category.name, self.navigate, self.NAVIGATION_HOME, category)
		elif category.parent == self.root_category:
			self.navigation_bar.add_with_id(category.name, self.navigate, self.NAVIGATION_CATEGORY, category)
		else:
			self.navigation_bar.add_with_id(category.name, self.navigate, self.NAVIGATION_SUB_CATEGORY, category)

	def show_search_results(self, terms):
		# Load packages into self.tree_search
		model_applications = gtk.TreeStore(gtk.gdk.Pixbuf, str, gtk.gdk.Pixbuf, object)

		self.model_filter = model_applications.filter_new()
		self.model_filter.set_visible_func(self.visible_func)

#		self.packages.sort()
		for package in self.packages:
			termss = terms.split(' ')
			if len(termss) > 1:
				found = False
			else:
				found = True
			for term in termss:
				aux = found
				if term.strip() != '':
					if term in package.pkg.name:
						found = True
					else:
						if package.pkg.candidate is not None:
							if self.prefs["search_in_summary"] and ((term in package.pkg.candidate.summary) or (term.capitalize() in package.pkg.candidate.summary)):
								found = True
							elif self.prefs["search_in_description"] and ((term in package.pkg.candidate.description) or (term.capitalize() in package.pkg.candidate.description)):
								found = True
							else:
								found = False
						else:
							found = False
			if aux and found:
				iter = model_applications.insert_before(None, None)
				if package.pkg.is_installed:
					model_applications.set_value(iter, 0, gtk.gdk.pixbuf_new_from_file("/usr/lib/tuquito/tuquito-software-manager/data/installed.png"))
				else:
					model_applications.set_value(iter, 0, gtk.gdk.pixbuf_new_from_file("/usr/lib/tuquito/tuquito-software-manager/data/available.png"))

				summary = ""
				if package.pkg.candidate is not None:
					summary = package.pkg.candidate.summary
					summary = unicode(summary, 'UTF-8', 'replace')
					summary = summary.replace("<", "&lt;")
					summary = summary.replace("&", "&amp;")

				model_applications.set_value(iter, 1, "%s\n<small><span foreground='#555555'>%s</span></small>" % (package.name, summary.capitalize()))
				model_applications.set_value(iter, 3, package)

		self.tree_search.set_model(self.model_filter)
		cant = len(model_applications)
		del model_applications
		self.navigation_bar.add_with_id('%s (%s)' % (_("Search results"), cant), self.navigate, self.NAVIGATION_CATEGORY, "search")

	def visible_func(self, model, iter):
		package = model.get_value(iter, 3)
		if package is not None:
			if package.pkg is not None:
				if package.pkg.is_installed and self.prefs["installed_packages_visible"]:
					return True
				elif (not package.pkg.is_installed) and self.prefs["available_packages_visible"]:
					return True
		return False

	def show_package(self, package):
		theme = gtk.icon_theme_get_default()
		self.current_package = package
		icon = None
		if theme.has_icon(package.pkg.name):
			iconInfo = theme.lookup_icon(package.pkg.name, 72, 0)
			fileName = iconInfo.get_filename()
			baseName = os.path.basename(fileName)
			if '.xpm' in fileName:
				svgFile = os.path.join(home, '.tuquito/tuquito-software-manager/apps/' + baseName.replace('.xpm', '.svg'))
				if not os.path.exists(svgFile):
					os.system('mkdir -p ' + os.path.join(home, ".tuquito/tuquito-software-manager/apps/"))
					os.system('cp ' + fileName + ' ' + svgFile)
				icon = svgFile
			elif iconInfo and os.path.exists(fileName):
				icon = fileName
		if icon == None:
			iconInfo = theme.lookup_icon("applications-other", 72, 0)
			if iconInfo and os.path.exists(iconInfo.get_filename()):
				icon = iconInfo.get_filename()
		# Load package info
		subs = {}
		subs['icon'] = icon
		subs['txtVersion'] = _("Version:")
		subs['txtSize'] = _("Size:")
		subs['loading_txt'] = _("Loading score...")
		subs['votes'] = _('votes')
		subs['vbad'] = _('Very bad')
		subs['ntbad'] = _('Not that bad')
		subs['average'] = _('Average')
		subs['good'] = _('Good')
		subs['excellent'] = _('Excellent')
		subs['timeout_error'] = _('Error loading data')
		subs['just_now'] = _('Just now')
		subs['more'] = _('More...')
		subs['nick'] = self.prefs["username"]
		subs['pass'] = base64.b64decode(self.prefs["password"])
		subs['comment'] = _('Comment')
		subs['comments'] = _('comments')
		subs['send'] = _('Send')
		subs['loading_comments'] = _('Loading comments...')
		a = package.name.split('-')
		c = []
		for b in a:
			c.append(b.capitalize())
		subs['appname'] = ' '.join(c)
		subs['pkgname'] = package.pkg.name
		subs['description'] = package.pkg.candidate.description
		subs['description'] = subs['description'].replace('\n','<br>\n')
		subs['summary'] = package.pkg.candidate.summary.capitalize()

		strSize = str(package.pkg.candidate.size) + _("B")
		if package.pkg.candidate.size >= 1000:
			strSize = str(package.pkg.candidate.size / 1000) + _("KB")
		if package.pkg.candidate.size >= 1000000:
			strSize = str(package.pkg.candidate.size / 1000000) + _("MB")
		if package.pkg.candidate.size >= 1000000000:
			strSize = str(package.pkg.candidate.size / 1000000000) + _("GB")
		subs['size'] = strSize

		if len(package.pkg.candidate.homepage) > 0:
			subs['website'] = '<a href="javascript:action_website_clicked()">' + _("Website") + '</a> -'
		else:
			subs['website'] = ""

		direction = gtk.widget_get_default_direction()
	        if direction ==  gtk.TEXT_DIR_RTL:
	            subs['text_direction'] = 'DIR="RTL"'
	        elif direction ==  gtk.TEXT_DIR_LTR:
	            subs['text_direction'] = 'DIR="LTR"'

		subs['remove_button_label'] = _("Remove")
		subs['install_button_label'] = _("Install")
		subs['update_button_label'] = _("Update")

		if package.pkg.is_installed:
			subs['version'] = package.pkg.installed.version
			subs['action'] = 'remove'
			if package.pkg.candidate.version > package.pkg.installed.version:
				subs['action'] = 'update'
		else:
			subs['version'] = package.pkg.candidate.version
			subs['action'] = 'install'

		template = open("/usr/lib/tuquito/tuquito-software-manager/data/templates/PackageView.html").read()
		html = string.Template(template).safe_substitute(subs)
		self.packageBrowser.load_html_string(html, "file:/")

		# Update the navigation bar
		self.navigation_bar.add_with_id(subs['appname'], self.navigate, self.NAVIGATION_ITEM, package)

if __name__ == "__main__":
	model = Classes.Model()
	Application()
	gtk.main()
